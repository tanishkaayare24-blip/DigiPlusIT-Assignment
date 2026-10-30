"""Turn database rows into JSON-friendly dicts for the API."""
from datetime import date

from app.core.constants import CLOSED_ITEM_STATUSES
from app.models.entities import ActionItem, Brief, KBDoc, Link, Meeting, Nudge, Participant


def iso(value) -> str | None:
    return value.isoformat() if value else None


def days_overdue(item: ActionItem, today: date | None = None) -> int:
    today = today or date.today()
    if item.status in CLOSED_ITEM_STATUSES or not item.due_date:
        return 0
    return max(0, (today - item.due_date).days)


def item_dict(item: ActionItem) -> dict:
    return {
        "id": item.id, "chain_id": item.chain_id, "meeting_id": item.meeting_id,
        "meeting_title": item.meeting.title if item.meeting else "",
        "title": item.title, "owner": item.owner, "due_date": iso(item.due_date),
        "status": item.status, "priority": item.priority, "outcome": item.outcome,
        "ai_suggested": item.ai_suggested, "carry_count": item.carry_count,
        "parent_item_id": item.parent_item_id, "carried_to_id": item.carried_to_id,
        "days_overdue": days_overdue(item), "is_closed": item.status in CLOSED_ITEM_STATUSES,
        "created_at": iso(item.created_at), "updated_at": iso(item.updated_at), "closed_at": iso(item.closed_at),
    }


def participant_dict(p: Participant) -> dict:
    return {"id": p.id, "name": p.name, "email": p.email, "role": p.role, "attended": p.attended}


def meeting_summary(m: Meeting) -> dict:
    return {
        "id": m.id, "title": m.title, "type": m.type, "status": m.status,
        "scheduled_at": iso(m.scheduled_at), "previous_meeting_id": m.previous_meeting_id,
        "participant_count": len(m.participants),
        "open_item_count": sum(1 for i in m.items if i.carried_to_id is None and i.status not in CLOSED_ITEM_STATUSES),
        "created_at": iso(m.created_at), "updated_at": iso(m.updated_at),
    }


def meeting_full(m: Meeting) -> dict:
    return {
        **meeting_summary(m),
        "agenda": m.agenda, "raw_notes": m.raw_notes, "summary": m.summary,
        "decisions": m.decisions or [], "open_questions": m.open_questions or [], "risks": m.risks or [],
        "participants": [participant_dict(p) for p in m.participants],
    }


def doc_dict(d: KBDoc, with_content: bool = True) -> dict:
    out = {"id": d.id, "title": d.title, "tags": d.tags or [], "updated_at": iso(d.updated_at)}
    if with_content:
        out["content"] = d.content
    else:
        out["snippet"] = d.content[:180] + ("..." if len(d.content) > 180 else "")
    return out


def link_dict(link: Link, title: str) -> dict:
    kind = "doc" if link.doc_id else "meeting"
    return {"id": link.id, "kind": kind, "target_id": link.doc_id or link.target_meeting_id, "title": title,
            "item_id": link.item_id, "reason": link.reason, "score": round(link.score, 3), "source": link.source}


def brief_dict(b: Brief) -> dict:
    return {"id": b.id, "person_name": b.person_name, "content": b.content,
            "generated_by": b.generated_by, "created_at": iso(b.created_at)}


def nudge_dict(n: Nudge) -> dict:
    return {"id": n.id, "item_id": n.item_id, "recipient": n.recipient, "reason_code": n.reason_code,
            "message": n.message, "generated_by": n.generated_by, "sent_at": iso(n.sent_at),
            "created_at": iso(n.created_at)}
