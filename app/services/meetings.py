"""Meetings and handovers: CRUD, lifecycle, carry-forward and the history timeline."""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import constants as C
from app.core.errors import AppError, not_found
from app.core.logging import log_event
from app.models.entities import ActionItem, ItemEvent, Meeting, MeetingEvent, Participant, utcnow
from app.schemas.api import MeetingIn
from app.services.items import add_event

logger = logging.getLogger("app.meetings")


def get_meeting(db: Session, meeting_id: int) -> Meeting:
    meeting = db.get(Meeting, meeting_id)
    if not meeting or meeting.deleted_at:
        raise not_found("Meeting", meeting_id)
    return meeting


def list_meetings(db: Session, include_archived: bool = True) -> list[Meeting]:
    query = select(Meeting).where(Meeting.deleted_at.is_(None))
    if not include_archived:
        query = query.where(Meeting.status != "archived")
    return list(db.scalars(query.order_by(Meeting.scheduled_at.desc().nulls_last(), Meeting.id.desc())))


def add_meeting_event(db: Session, meeting: Meeting, event_type: str, note: str = "") -> None:
    db.add(MeetingEvent(meeting_id=meeting.id, event_type=event_type, note=note))


def _check_previous(db: Session, previous_id: int | None, own_id: int | None = None) -> None:
    if previous_id is None:
        return
    if previous_id == own_id:
        raise AppError(422, "validation_error", "A meeting cannot follow itself.")
    get_meeting(db, previous_id)


def _apply(meeting: Meeting, data: MeetingIn) -> None:
    meeting.title, meeting.type, meeting.agenda = data.title, data.type, data.agenda
    meeting.raw_notes, meeting.decisions = data.raw_notes, data.decisions
    meeting.scheduled_at, meeting.previous_meeting_id = data.scheduled_at, data.previous_meeting_id
    meeting.participants = [Participant(**p.model_dump()) for p in data.participants]


def create_meeting(db: Session, data: MeetingIn) -> Meeting:
    _check_previous(db, data.previous_meeting_id)
    meeting = Meeting(status="draft")
    _apply(meeting, data)
    db.add(meeting)
    db.flush()
    add_meeting_event(db, meeting, "created", f"{meeting.type.title()} created as draft")
    db.commit()
    log_event(logger, "meeting_created", f"Meeting {meeting.id} created", meeting_id=meeting.id,
              meeting_type=meeting.type, participants=len(meeting.participants))
    return meeting


def update_meeting(db: Session, meeting_id: int, data: MeetingIn) -> Meeting:
    meeting = get_meeting(db, meeting_id)
    if meeting.status == "archived":
        raise AppError(409, "meeting_archived", "Archived meetings are read-only.")
    _check_previous(db, data.previous_meeting_id, meeting.id)
    _apply(meeting, data)
    add_meeting_event(db, meeting, "edited", "Details updated")
    db.commit()
    log_event(logger, "meeting_updated", f"Meeting {meeting.id} updated", meeting_id=meeting.id)
    return meeting


def delete_meeting(db: Session, meeting_id: int) -> None:
    meeting = get_meeting(db, meeting_id)
    meeting.deleted_at = utcnow()
    db.commit()
    log_event(logger, "meeting_deleted", f"Meeting {meeting.id} soft-deleted", meeting_id=meeting.id)


def change_status(db: Session, meeting_id: int, new_status: str) -> Meeting:
    meeting = get_meeting(db, meeting_id)
    old = meeting.status
    if new_status == old:
        return meeting
    allowed = C.MEETING_TRANSITIONS[old]
    if new_status not in allowed:
        nice = ", ".join(sorted(allowed)) or "none (archived is final)"
        raise AppError(409, "invalid_transition",
                       f"Cannot move a meeting from '{old}' to '{new_status}'. Allowed next steps: {nice}.")
    meeting.status = new_status
    add_meeting_event(db, meeting, "status_changed", f"{old} -> {new_status}")
    db.commit()
    log_event(logger, "meeting_status_changed", f"Meeting {meeting.id} {old} -> {new_status}",
              meeting_id=meeting.id, from_status=old, to_status=new_status)
    return meeting


def carry_over(db: Session, meeting_id: int, from_meeting_id: int | None) -> list[ActionItem]:
    """Copy every unclosed, not-yet-carried item from the source meeting into this one, keeping the chain."""
    target = get_meeting(db, meeting_id)
    source_id = from_meeting_id or target.previous_meeting_id
    if not source_id:
        raise AppError(422, "no_source_meeting", "Pick the previous meeting to carry items from.")
    if source_id == target.id:
        raise AppError(422, "validation_error", "A meeting cannot carry items from itself.")
    if target.status == "archived":
        raise AppError(409, "meeting_archived", "You cannot carry items into an archived meeting.")
    source = get_meeting(db, source_id)

    to_copy = [i for i in source.items if i.carried_to_id is None and i.status not in C.CLOSED_ITEM_STATUSES]
    copies = []
    for old in to_copy:
        new = ActionItem(meeting_id=target.id, title=old.title, owner=old.owner, due_date=old.due_date,
                         status=old.status, priority=old.priority, ai_suggested=old.ai_suggested,
                         origin_item_id=old.chain_id, parent_item_id=old.id, carry_count=old.carry_count + 1)
        db.add(new)
        db.flush()
        old.carried_to_id = new.id
        note = f"Carried from '{source.title}' to '{target.title}' (carry #{new.carry_count})"
        add_event(db, old, C.EV_CARRIED, str(source.id), str(target.id), note)
        add_event(db, new, C.EV_CARRIED, str(source.id), str(target.id), note)
        copies.append(new)
    if not target.previous_meeting_id:
        target.previous_meeting_id = source.id
    add_meeting_event(db, target, "items_carried_over", f"{len(copies)} open items carried from '{source.title}'")
    db.commit()
    log_event(logger, "items_carried_over", f"{len(copies)} items carried {source.id} -> {target.id}",
              from_meeting_id=source.id, to_meeting_id=target.id, count=len(copies),
              item_ids=[c.id for c in copies])
    return copies


def timeline(db: Session, meeting: Meeting) -> list[dict]:
    """Meeting events plus events of items in this meeting, newest first."""
    rows = [{"at": e.created_at, "kind": "meeting", "type": e.event_type, "text": e.note}
            for e in db.scalars(select(MeetingEvent).where(MeetingEvent.meeting_id == meeting.id))]
    titles = {i.id: i.title for i in meeting.items}
    for e in db.scalars(select(ItemEvent).where(ItemEvent.item_id.in_(titles.keys()))):
        rows.append({"at": e.created_at, "kind": "item", "type": e.event_type, "item_id": e.item_id,
                     "text": _event_text(e, titles.get(e.item_id, ""))})
    rows.sort(key=lambda r: r["at"], reverse=True)
    return [{**r, "at": r["at"].isoformat()} for r in rows[:60]]


def _event_text(e: ItemEvent, title: str) -> str:
    if e.event_type == C.EV_REASSIGNED:
        return f"'{title}' reassigned from {e.from_value or 'nobody'} to {e.to_value or 'nobody'}"
    if e.event_type == C.EV_CLOSED:
        return f"'{title}' closed as {e.to_value}: {e.note}"
    if e.event_type == C.EV_STATUS:
        return f"'{title}' {e.from_value} -> {e.to_value}"
    if e.event_type == C.EV_CREATED:
        return f"'{title}' created" + (f" ({e.note})" if e.note else "")
    if e.event_type == C.EV_UPDATED:
        return f"'{title}' {e.note} changed: {e.from_value or '-'} -> {e.to_value or '-'}"
    return f"'{title}': {e.note or e.event_type}"
