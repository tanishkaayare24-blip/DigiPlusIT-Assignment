"""Action items, knowledge base, dashboard, links, nudges and system endpoints."""
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.ai.runner import ai_status
from app.core import constants as C
from app.core.db import get_db
from app.core.errors import not_found
from app.models.entities import ActionItem, KBDoc, Link, Meeting, Participant, utcnow
from app.schemas.api import ItemIn, ItemUpdate, KBDocIn
from app.services import ai_features, health, items, meetings, seed
from app.services.serializers import doc_dict, item_dict, meeting_summary, nudge_dict

router = APIRouter(tags=["workspace"])


# --- Action items -----------------------------------------------------------
@router.get("/api/items")
def list_items(owner: str | None = None, status: str | None = Query(None, pattern="^(" + "|".join(C.ITEM_STATUSES) + ")$"),
               overdue: bool = False, meeting_id: int | None = None, include_closed: bool = True,
               db: Session = Depends(get_db)):
    return [item_dict(i) for i in items.list_items(db, owner, status, overdue, meeting_id, include_closed)]


@router.post("/api/items", status_code=201)
def create_item(body: ItemIn, db: Session = Depends(get_db)):
    return item_dict(items.create_item(db, body))


@router.get("/api/items/{item_id}")
def get_item(item_id: int, db: Session = Depends(get_db)):
    item = items.get_item(db, item_id)
    chain, events = items.item_history(db, item)
    return {**item_dict(item), "chain": [item_dict(i) for i in chain],
            "history": [{"id": e.id, "item_id": e.item_id, "meeting_id": e.meeting_id, "type": e.event_type,
                         "from": e.from_value, "to": e.to_value, "note": e.note, "at": e.created_at.isoformat()}
                        for e in events]}


@router.patch("/api/items/{item_id}")
def update_item(item_id: int, body: ItemUpdate, db: Session = Depends(get_db)):
    return item_dict(items.update_item(db, item_id, body))


# --- Knowledge base ---------------------------------------------------------
def _get_doc(db: Session, doc_id: int) -> KBDoc:
    doc = db.get(KBDoc, doc_id)
    if not doc or doc.deleted_at:
        raise not_found("Document", doc_id)
    return doc


@router.get("/api/kb")
def list_docs(q: str = "", db: Session = Depends(get_db)):
    query = select(KBDoc).where(KBDoc.deleted_at.is_(None))
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.where(or_(KBDoc.title.ilike(like), KBDoc.content.ilike(like), KBDoc.tags.cast(str).ilike(like)))
    return [doc_dict(d, with_content=False) for d in db.scalars(query.order_by(KBDoc.title))]


@router.post("/api/kb", status_code=201)
def create_doc(body: KBDocIn, db: Session = Depends(get_db)):
    doc = KBDoc(**body.model_dump())
    db.add(doc)
    db.commit()
    return doc_dict(doc)


@router.get("/api/kb/{doc_id}")
def get_doc(doc_id: int, db: Session = Depends(get_db)):
    doc = _get_doc(db, doc_id)
    used_by = db.scalars(select(Meeting).join(Link, Link.meeting_id == Meeting.id).where(
        Link.doc_id == doc.id, Link.removed.is_(False), Meeting.deleted_at.is_(None)).distinct())
    return {**doc_dict(doc), "linked_meetings": [meeting_summary(m) for m in used_by]}


@router.put("/api/kb/{doc_id}")
def update_doc(doc_id: int, body: KBDocIn, db: Session = Depends(get_db)):
    doc = _get_doc(db, doc_id)
    doc.title, doc.content, doc.tags = body.title, body.content, body.tags
    db.commit()
    return doc_dict(doc)


@router.delete("/api/kb/{doc_id}", status_code=204)
def delete_doc(doc_id: int, db: Session = Depends(get_db)):
    _get_doc(db, doc_id).deleted_at = utcnow()
    db.commit()


# --- Links & nudges -----------------------------------------------------------
@router.delete("/api/links/{link_id}", status_code=204)
def remove_link(link_id: int, db: Session = Depends(get_db)):
    ai_features.remove_link(db, link_id)


@router.post("/api/nudges/{nudge_id}/sent")
def nudge_sent(nudge_id: int, db: Session = Depends(get_db)):
    return nudge_dict(health.mark_nudge_sent(db, nudge_id))


# --- Dashboard ------------------------------------------------------------------
@router.get("/api/people")
def people(db: Session = Depends(get_db)):
    names = set(db.scalars(select(Participant.name).join(Meeting).where(Meeting.deleted_at.is_(None))))
    names |= {o for o in db.scalars(select(ActionItem.owner)) if o}
    return sorted(names)


@router.get("/api/dashboard")
def dashboard(person: str = "", db: Session = Depends(get_db)):
    now = utcnow()
    upcoming = [m for m in meetings.list_meetings(db, include_archived=False)
                if m.status in ("draft", "scheduled") and (not m.scheduled_at or m.scheduled_at >= now.replace(hour=0, minute=0))]
    upcoming.sort(key=lambda m: m.scheduled_at or now)
    open_items = items.list_items(db, include_closed=False)
    mine = [i for i in open_items if person and i.owner.lower() == person.lower()]
    return {
        "radar": health.risk_radar(db),
        "my_items": [item_dict(i) for i in mine],
        "upcoming": [meeting_summary(m) for m in upcoming[:5]],
        "stats": {"open_items": len(open_items), "overdue": sum(1 for i in open_items if items.is_overdue(i)),
                  "unowned": sum(1 for i in open_items if not i.owner), "today": date.today().isoformat()},
    }


# --- System ---------------------------------------------------------------------
@router.get("/health")
def health_check():
    return {"status": "ok"}


@router.get("/api/ai/status")
def get_ai_status():
    return ai_status.as_dict()


@router.post("/api/demo/reset")
def reset_demo(db: Session = Depends(get_db)):
    seed.reset_demo(db)
    return {"status": "reset"}
