"""Handoff Health Score, Nudge Engine and Risk Radar."""
import json
import logging
from collections import Counter
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import prompts
from app.ai.fallback import fallback_client
from app.ai.runner import run_structured
from app.ai.schemas import NudgesOut
from app.core import constants as C
from app.core.errors import AppError, not_found
from app.core.logging import log_event
from app.models.entities import ActionItem, Brief, Link, Meeting, Nudge, utcnow
from app.services.items import active_items_query, add_event
from app.services.meetings import get_meeting, list_meetings
from app.services.serializers import days_overdue, item_dict

logger = logging.getLogger("app.health")

NUDGE_CODES = {"overdue", "stale_carry", "no_owner", "no_due_date", "missed_no_brief", "bus_factor"}


def _organiser(meeting: Meeting) -> str:
    for p in meeting.participants:
        if any(k in p.role.lower() for k in ("organis", "organiz", "lead", "manager", "pm")):
            return p.name
    return meeting.participants[0].name if meeting.participants else ""


def compute_health(db: Session, meeting: Meeting) -> dict:
    """Start at 100 and subtract transparent penalties. Each reason says what is wrong and who can fix it."""
    open_items = [i for i in meeting.items if i.carried_to_id is None and i.status not in C.CLOSED_ITEM_STATUSES]
    briefed = {b.person_name.lower() for b in db.scalars(select(Brief).where(Brief.meeting_id == meeting.id))}
    links = list(db.scalars(select(Link).where(Link.meeting_id == meeting.id, Link.removed.is_(False))))
    doc_links = [l for l in links if l.doc_id]
    organiser = _organiser(meeting)
    raw: list[dict] = []

    for item in open_items:
        base = {"item_id": item.id, "item_title": item.title, "carry_count": item.carry_count}
        if not item.owner:
            raw.append({**base, "code": "no_owner", "recipient": organiser,
                        "message": f"'{item.title}' has no owner."})
        elif not item.due_date:
            raw.append({**base, "code": "no_due_date", "recipient": item.owner,
                        "message": f"'{item.title}' ({item.owner}) has no due date."})
        overdue = days_overdue(item)
        if overdue:
            raw.append({**base, "code": "overdue", "recipient": item.owner or organiser, "days_overdue": overdue,
                        "message": f"'{item.title}' is {overdue} days overdue."})
        if item.carry_count >= C.STALE_CARRY_THRESHOLD:
            raw.append({**base, "code": "stale_carry", "recipient": item.owner or organiser,
                        "message": f"'{item.title}' has been carried over {item.carry_count} times."})

    if meeting.status in ("completed", "archived") or meeting.type == "handover":
        for p in meeting.participants:
            if p.attended != "yes" and p.name.lower() not in briefed:
                why = "did not attend" if p.attended == "no" else "never responded"
                raw.append({"code": "missed_no_brief", "recipient": p.name, "meeting_title": meeting.title,
                            "message": f"{p.name} {why} and has not received a catch-up brief."})

    if meeting.decisions and not doc_links:
        raw.append({"code": "decisions_no_kb", "recipient": organiser,
                    "message": f"{len(meeting.decisions)} decisions are not linked to any knowledge-base doc."})
    if meeting.type == "handover" and not links:
        raw.append({"code": "handover_no_kb", "recipient": organiser,
                    "message": "This handover has no knowledge-base links, so context lives only in people's heads."})

    owners = Counter(i.owner for i in open_items if i.owner)
    owned_total = sum(owners.values())
    if owned_total >= C.BUS_FACTOR_MIN_ITEMS:
        top, count = owners.most_common(1)[0]
        share = count / owned_total
        if share > C.BUS_FACTOR_SHARE:
            raw.append({"code": "bus_factor", "recipient": top, "share": round(share * 100),
                        "message": f"{top} owns {round(share * 100)}% of the open items (bus-factor risk)."})

    reasons, used = [], Counter()
    for r in raw:
        per, cap = C.HEALTH_RULES[r["code"]]
        penalty = max(0, min(per, cap - used[r["code"]]))
        used[r["code"]] += penalty
        reasons.append({**r, "penalty": penalty})
    score = max(0, 100 - sum(used.values()))
    band = "green" if score >= C.HEALTH_GREEN else "amber" if score >= C.HEALTH_AMBER else "red"
    reasons.sort(key=lambda r: -r["penalty"])
    return {"score": score, "band": band, "reasons": reasons, "open_items": len(open_items)}


# --- Nudge engine ------------------------------------------------------------
def generate_nudges(db: Session, meeting_id: int) -> tuple[list[Nudge], str]:
    meeting = get_meeting(db, meeting_id)
    health = compute_health(db, meeting)
    problems = []
    for idx, r in enumerate(health["reasons"]):
        if r["code"] in NUDGE_CODES and r.get("recipient"):
            problems.append({**r, "key": f"n{idx}", "meeting_title": meeting.title})
    # one nudge per (recipient, item, code); overdue covers stale for the same item
    seen, unique = set(), []
    for p in problems:
        sig = (p["recipient"], p.get("item_id"), "overdue" if p["code"] == "stale_carry" else p["code"])
        if sig not in seen:
            seen.add(sig)
            unique.append(p)

    for old in db.scalars(select(Nudge).where(Nudge.meeting_id == meeting.id, Nudge.sent_at.is_(None))):
        db.delete(old)
    if not unique:
        db.commit()
        return [], "ai"

    slim = [{k: p.get(k) for k in ("key", "code", "recipient", "item_title", "days_overdue", "carry_count",
                                    "share", "message")} for p in unique]
    user = prompts.NUDGE_USER.format(title=meeting.title, problems=json.dumps(slim))
    outcome = run_structured("nudge", prompts.NUDGE_SYSTEM, user, NudgesOut, lambda: fallback_client.nudges(unique))
    texts = {n.key: n.message for n in outcome.data.nudges}
    template_texts = {n.key: n.message for n in fallback_client.nudges(unique).nudges}

    created = []
    for p in unique:
        nudge = Nudge(meeting_id=meeting.id, item_id=p.get("item_id"), recipient=p["recipient"],
                      reason_code=p["code"], message=texts.get(p["key"]) or template_texts[p["key"]],
                      generated_by=outcome.mode)
        db.add(nudge)
        created.append(nudge)
    db.commit()
    log_event(logger, "nudges_generated", f"{len(created)} nudges drafted for meeting {meeting.id}",
              meeting_id=meeting.id, count=len(created), mode=outcome.mode)
    return created, outcome.mode


def mark_nudge_sent(db: Session, nudge_id: int) -> Nudge:
    nudge = db.get(Nudge, nudge_id)
    if not nudge:
        raise not_found("Nudge", nudge_id)
    if nudge.sent_at:
        raise AppError(409, "already_sent", "This nudge was already marked as sent.")
    nudge.sent_at = utcnow()
    if nudge.item_id and (item := db.get(ActionItem, nudge.item_id)):
        add_event(db, item, C.EV_NUDGED, to_value=nudge.recipient, note=f"Nudge sent ({nudge.reason_code})")
    db.commit()
    log_event(logger, "nudge_sent", f"Nudge {nudge.id} marked sent", nudge_id=nudge.id, meeting_id=nudge.meeting_id,
              item_id=nudge.item_id, recipient=nudge.recipient, reason_code=nudge.reason_code)
    return nudge


# --- Risk radar ----------------------------------------------------------------
def item_risk(item: ActionItem) -> tuple[int, list[str]]:
    score, why = 0, []
    overdue = days_overdue(item)
    if overdue:
        score += 10 + min(overdue, 30)
        why.append(f"{overdue}d overdue")
    if item.carry_count >= C.STALE_CARRY_THRESHOLD:
        score += 8 * item.carry_count
        why.append(f"carried {item.carry_count}x")
    if not item.owner:
        score += 15
        why.append("no owner")
    if item.status == "blocked":
        score += 10
        why.append("blocked")
    if not item.due_date:
        score += 5
        why.append("no due date")
    return score, why


def risk_radar(db: Session) -> dict:
    meetings = [m for m in list_meetings(db) if m.status != "archived"]
    scored = []
    for m in meetings:
        h = compute_health(db, m)
        scored.append({"id": m.id, "title": m.title, "type": m.type, "status": m.status, "score": h["score"],
                       "band": h["band"], "top_reasons": [r["message"] for r in h["reasons"][:3]]})
    scored.sort(key=lambda s: s["score"])

    items = db.scalars(active_items_query().where(ActionItem.status.not_in(C.CLOSED_ITEM_STATUSES)))
    risky = []
    for item in items:
        score, why = item_risk(item)
        if score:
            risky.append({**item_dict(item), "risk_score": score, "risk_reasons": why})
    risky.sort(key=lambda r: -r["risk_score"])
    return {"meetings": [s for s in scored if s["band"] != "green"][:C.RISK_RADAR_LIMIT] or scored[:3],
            "items": risky[:C.RISK_RADAR_LIMIT],
            "workspace_score": round(sum(s["score"] for s in scored) / len(scored)) if scored else 100,
            "as_of": date.today().isoformat()}
