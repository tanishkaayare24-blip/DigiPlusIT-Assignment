"""Action items: create, update (with full history), list and filter."""
import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import constants as C
from app.core.errors import AppError, not_found
from app.core.logging import log_event
from app.models.entities import ActionItem, ItemEvent, Meeting, utcnow
from app.schemas.api import ItemIn, ItemUpdate
from app.services.serializers import days_overdue

logger = logging.getLogger("app.items")


def add_event(db: Session, item: ActionItem, event_type: str, from_value: str = "", to_value: str = "",
              note: str = "") -> None:
    db.add(ItemEvent(item_id=item.id, chain_id=item.chain_id, meeting_id=item.meeting_id, event_type=event_type,
                     from_value=from_value or "", to_value=to_value or "", note=note))


def get_item(db: Session, item_id: int) -> ActionItem:
    item = db.get(ActionItem, item_id)
    if not item or (item.meeting and item.meeting.deleted_at):
        raise not_found("Action item", item_id)
    return item


def active_items_query():
    """Items that are 'live': not superseded by a carried-over copy and in a non-deleted meeting."""
    return (select(ActionItem).join(Meeting, ActionItem.meeting_id == Meeting.id)
            .where(ActionItem.carried_to_id.is_(None), Meeting.deleted_at.is_(None)))


def create_item(db: Session, data: ItemIn) -> ActionItem:
    meeting = db.get(Meeting, data.meeting_id)
    if not meeting or meeting.deleted_at:
        raise not_found("Meeting", data.meeting_id)
    if meeting.status == "archived":
        raise AppError(409, "meeting_archived", "You cannot add items to an archived meeting.")
    item = ActionItem(meeting_id=meeting.id, title=data.title.strip(), owner=data.owner.strip(),
                      due_date=data.due_date, priority=data.priority, ai_suggested=data.ai_suggested)
    db.add(item)
    db.flush()
    add_event(db, item, C.EV_CREATED, to_value=item.title,
              note="Accepted from AI recap" if item.ai_suggested else "")
    db.commit()
    log_event(logger, "item_created", f"Item {item.id} created", item_id=item.id, meeting_id=meeting.id,
              owner=item.owner or None, ai_suggested=item.ai_suggested)
    return item


def update_item(db: Session, item_id: int, data: ItemUpdate) -> ActionItem:
    item = get_item(db, item_id)
    if item.carried_to_id:
        raise AppError(409, "item_superseded",
                       f"This item was carried over to item {item.carried_to_id}. Please update that one instead.")
    changes = data.model_dump(exclude_unset=True)

    if "title" in changes and changes["title"] and changes["title"] != item.title:
        add_event(db, item, C.EV_UPDATED, item.title, changes["title"], note="title")
        item.title = changes["title"].strip()
    if "owner" in changes and changes["owner"] is not None and changes["owner"].strip() != item.owner:
        new_owner = changes["owner"].strip()
        add_event(db, item, C.EV_REASSIGNED, item.owner, new_owner)
        log_event(logger, "item_reassigned", f"Item {item.id} reassigned", item_id=item.id,
                  from_owner=item.owner or None, to_owner=new_owner or None)
        item.owner = new_owner
    if "due_date" in changes and changes["due_date"] != item.due_date:
        new_due = changes["due_date"]  # explicit null clears the date
        add_event(db, item, C.EV_UPDATED, str(item.due_date or ""), str(new_due or ""), note="due_date")
        item.due_date = new_due
    if changes.get("priority") and changes["priority"] != item.priority:
        add_event(db, item, C.EV_UPDATED, item.priority, changes["priority"], note="priority")
        item.priority = changes["priority"]
    if changes.get("status") and changes["status"] != item.status:
        _change_status(db, item, changes["status"], (changes.get("outcome") or "").strip())
    elif changes.get("outcome") is not None and item.status in C.CLOSED_ITEM_STATUSES:
        item.outcome = changes["outcome"].strip()

    db.commit()
    return item


def _change_status(db: Session, item: ActionItem, new_status: str, outcome: str) -> None:
    old = item.status
    item.status = new_status
    if new_status in C.CLOSED_ITEM_STATUSES:
        item.outcome = outcome
        item.closed_at = utcnow()
        add_event(db, item, C.EV_CLOSED, old, new_status, note=outcome)
        log_event(logger, "item_closed", f"Item {item.id} closed as {new_status}", item_id=item.id,
                  status=new_status, outcome=outcome, carry_count=item.carry_count)
    else:
        if old in C.CLOSED_ITEM_STATUSES:
            item.closed_at = None
        add_event(db, item, C.EV_STATUS, old, new_status)
        log_event(logger, "item_status_changed", f"Item {item.id} {old} -> {new_status}", item_id=item.id,
                  from_status=old, to_status=new_status)


def list_items(db: Session, owner: str | None = None, status: str | None = None, overdue: bool = False,
               meeting_id: int | None = None, include_closed: bool = True) -> list[ActionItem]:
    query = active_items_query()
    if owner:
        query = query.where(ActionItem.owner == owner) if owner != "__none__" else query.where(ActionItem.owner == "")
    if status:
        query = query.where(ActionItem.status == status)
    elif not include_closed:
        query = query.where(ActionItem.status.not_in(C.CLOSED_ITEM_STATUSES))
    if meeting_id:
        query = query.where(ActionItem.meeting_id == meeting_id)
    if overdue:
        query = query.where(ActionItem.due_date < date.today(), ActionItem.status.not_in(C.CLOSED_ITEM_STATUSES))
    return list(db.scalars(query.order_by(ActionItem.due_date.is_(None), ActionItem.due_date, ActionItem.id)))


def item_history(db: Session, item: ActionItem) -> tuple[list[ActionItem], list[ItemEvent]]:
    chain = list(db.scalars(select(ActionItem).where(
        (ActionItem.id == item.chain_id) | (ActionItem.origin_item_id == item.chain_id)).order_by(ActionItem.id)))
    events = list(db.scalars(select(ItemEvent).where(ItemEvent.chain_id == item.chain_id).order_by(ItemEvent.id)))
    return chain, events


def is_overdue(item: ActionItem) -> bool:
    return days_overdue(item) > 0
