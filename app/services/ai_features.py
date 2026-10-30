"""AI-powered features: recap, catch-up brief, knowledge links. Each one falls back to basic mode safely."""
import json
import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import prompts
from app.ai.fallback import fallback_client
from app.ai.runner import run_structured
from app.ai.schemas import BriefOut, LinksOut, RecapOut
from app.core import constants as C
from app.core.errors import AppError, not_found
from app.core.logging import log_event
from app.models.entities import ActionItem, Brief, KBDoc, Link, Meeting
from app.schemas.api import ItemIn, RecapAccept
from app.services.items import create_item
from app.services.meetings import add_meeting_event, get_meeting
from app.services.retrieval import rank
from app.services.serializers import days_overdue

logger = logging.getLogger("app.ai_features")


# --- Recap ---------------------------------------------------------------
def generate_recap(db: Session, meeting_id: int, text: str) -> tuple[RecapOut, str]:
    meeting = get_meeting(db, meeting_id)
    people = [p.name for p in meeting.participants]
    today = date.today()
    user = prompts.RECAP_USER.format(today=today.isoformat(), title=meeting.title,
                                     participants=", ".join(people) or "unknown", text=text)
    outcome = run_structured("recap", prompts.RECAP_SYSTEM, user, RecapOut,
                             lambda: fallback_client.recap(text, people, today))
    log_event(logger, "recap_generated", f"Recap suggested for meeting {meeting.id}", meeting_id=meeting.id,
              mode=outcome.mode, input_chars=len(text), suggested_items=len(outcome.data.action_items))
    return outcome.data, outcome.mode


def accept_recap(db: Session, meeting_id: int, data: RecapAccept) -> Meeting:
    """Save only what the user reviewed and accepted. Nothing from the AI is saved without this step."""
    meeting = get_meeting(db, meeting_id)
    if meeting.status == "archived":
        raise AppError(409, "meeting_archived", "Archived meetings are read-only.")
    if data.summary:
        meeting.summary = data.summary
    meeting.decisions = _merge(meeting.decisions, data.decisions)
    meeting.open_questions = _merge(meeting.open_questions, data.open_questions)
    meeting.risks = _merge(meeting.risks, data.risks)
    if data.source_text and data.source_text not in (meeting.raw_notes or ""):
        meeting.raw_notes = ((meeting.raw_notes + "\n\n") if meeting.raw_notes else "") + data.source_text
    add_meeting_event(db, meeting, "recap_accepted",
                      f"Recap saved: {len(data.decisions)} decisions, {len(data.action_items)} items accepted")
    db.commit()
    for item in data.action_items:
        create_item(db, ItemIn(meeting_id=meeting.id, title=item.title, owner=item.owner,
                               due_date=item.due_date, priority=item.priority, ai_suggested=True))
    log_event(logger, "recap_accepted", f"Recap accepted for meeting {meeting.id}", meeting_id=meeting.id,
              decisions=len(data.decisions), items=len(data.action_items))
    db.refresh(meeting)
    return meeting


def _merge(existing: list | None, new: list[str]) -> list[str]:
    out = list(existing or [])
    out += [n for n in new if n not in out]
    return out


# --- Catch-up brief --------------------------------------------------------
def brief_context(db: Session, meeting: Meeting, person: str) -> dict:
    participant = next((p for p in meeting.participants if p.name.lower() == person.lower()), None)
    live = [i for i in meeting.items if i.carried_to_id is None]

    def view(i: ActionItem) -> dict:
        return {"title": i.title, "owner": i.owner or "unassigned", "status": i.status,
                "due_date": i.due_date.isoformat() if i.due_date else None,
                "days_overdue": days_overdue(i), "carry_count": i.carry_count}

    mine = [view(i) for i in live if i.owner.lower() == person.lower() and i.status not in C.CLOSED_ITEM_STATUSES]
    mine.sort(key=lambda i: -i["days_overdue"])
    return {
        "person": person, "role": participant.role if participant else "",
        "attendance": participant.attended if participant else "not_listed",
        "title": meeting.title, "type": meeting.type, "agenda": meeting.agenda,
        "summary": meeting.summary or meeting.raw_notes[:1500], "decisions": meeting.decisions or [],
        "risks": meeting.risks or [], "your_items": mine,
        "other_open_items": [view(i) for i in live if i.owner.lower() != person.lower()
                             and i.status not in C.CLOSED_ITEM_STATUSES][:10],
    }


def get_or_create_brief(db: Session, meeting_id: int, person: str, regenerate: bool) -> tuple[Brief, bool]:
    meeting = get_meeting(db, meeting_id)
    cached = db.scalars(select(Brief).where(Brief.meeting_id == meeting.id, Brief.person_name == person)
                        .order_by(Brief.id.desc())).first()
    if cached and not regenerate:
        log_event(logger, "brief_cache_hit", f"Brief for {person} served from cache", logging.DEBUG,
                  meeting_id=meeting.id)
        return cached, True
    ctx = brief_context(db, meeting, person)
    user = prompts.BRIEF_USER.format(today=date.today().isoformat(), person=person, context=json.dumps(ctx))
    outcome = run_structured("brief", prompts.BRIEF_SYSTEM, user, BriefOut, lambda: fallback_client.brief(ctx))
    brief = Brief(meeting_id=meeting.id, person_name=person, content=outcome.data.model_dump(),
                  generated_by=outcome.mode)
    db.add(brief)
    add_meeting_event(db, meeting, "brief_generated", f"Catch-up brief generated for {person}")
    db.commit()
    log_event(logger, "brief_generated", f"Brief generated for meeting {meeting.id}", meeting_id=meeting.id,
              person=person, mode=outcome.mode, regenerated=bool(cached), owned_items=len(ctx["your_items"]))
    return brief, False


# --- Knowledge links -------------------------------------------------------
def suggest_links(db: Session, meeting_id: int) -> tuple[int, str]:
    meeting = get_meeting(db, meeting_id)
    existing = list(db.scalars(select(Link).where(Link.meeting_id == meeting.id)))
    taken = {(l.doc_id, l.target_meeting_id) for l in existing}  # includes removed ones: never re-suggest

    candidates: dict[str, str] = {}
    titles: dict[str, str] = {}
    for doc in db.scalars(select(KBDoc).where(KBDoc.deleted_at.is_(None))):
        if (doc.id, None) not in taken:
            candidates[f"doc:{doc.id}"] = f"{doc.title} {' '.join(doc.tags or [])} {doc.content}"
            titles[f"doc:{doc.id}"] = doc.title
    for other in db.scalars(select(Meeting).where(Meeting.deleted_at.is_(None), Meeting.id != meeting.id)):
        if (None, other.id) not in taken:
            candidates[f"meeting:{other.id}"] = f"{other.title} {other.summary} {' '.join(other.decisions or [])}"
            titles[f"meeting:{other.id}"] = other.title

    query = " ".join([meeting.title, meeting.agenda, meeting.summary, meeting.raw_notes[:3000],
                      " ".join(meeting.decisions or []), " ".join(i.title for i in meeting.items)])
    ranked = [r for r in rank(query, candidates, C.LINK_SHORTLIST_SIZE) if r[1] >= C.LINK_MIN_SCORE]
    if not ranked:
        return 0, "basic"
    shortlist = [{"candidate_id": key, "title": titles[key], "keywords": kws, "score": round(score, 3),
                  "preview": candidates[key][:300]} for key, score, kws in ranked]
    scores = {s["candidate_id"]: s["score"] for s in shortlist}

    meeting_text = f"{meeting.title}\nAgenda: {meeting.agenda}\nDecisions: {meeting.decisions}\nSummary: {meeting.summary}"
    user = prompts.LINK_USER.format(meeting=meeting_text[:3000], candidates=json.dumps(
        [{k: s[k] for k in ("candidate_id", "title", "preview")} for s in shortlist]))
    system = prompts.LINK_SYSTEM.replace("{max_links}", str(C.LINK_MAX_RESULTS))
    outcome = run_structured("link", system, user, LinksOut,
                             lambda: fallback_client.links(shortlist, C.LINK_MAX_RESULTS))

    added = 0
    for pick in outcome.data.links[:C.LINK_MAX_RESULTS]:
        if pick.candidate_id not in scores:  # AI may only choose from the shortlist
            continue
        kind, raw_id = pick.candidate_id.split(":")
        db.add(Link(meeting_id=meeting.id, doc_id=int(raw_id) if kind == "doc" else None,
                    target_meeting_id=int(raw_id) if kind == "meeting" else None,
                    reason=pick.reason[:300], score=scores[pick.candidate_id], source=outcome.mode))
        added += 1
    add_meeting_event(db, meeting, "links_suggested", f"{added} knowledge links added")
    db.commit()
    log_event(logger, "links_suggested", f"{added} links added to meeting {meeting.id}", meeting_id=meeting.id,
              mode=outcome.mode, shortlist=len(shortlist), added=added)
    return added, outcome.mode


def remove_link(db: Session, link_id: int) -> None:
    link = db.get(Link, link_id)
    if not link or link.removed:
        raise not_found("Link", link_id)
    link.removed = True
    db.commit()
    log_event(logger, "link_removed", f"Link {link.id} removed by user", meeting_id=link.meeting_id, link_id=link.id)


def meeting_links(db: Session, meeting: Meeting) -> list[tuple[Link, str]]:
    out = []
    for link in db.scalars(select(Link).where(Link.meeting_id == meeting.id, Link.removed.is_(False))):
        target = db.get(KBDoc, link.doc_id) if link.doc_id else db.get(Meeting, link.target_meeting_id)
        if target and not target.deleted_at:
            out.append((link, target.title))
    return out

