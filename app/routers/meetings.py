"""Meeting / handover endpoints, including the AI panels shown on the meeting page."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.entities import Brief, Nudge
from app.schemas.api import BriefRequest, CarryOverIn, MeetingIn, RecapAccept, RecapRequest, StatusChange
from app.services import ai_features, health, meetings
from app.services.serializers import (brief_dict, item_dict, link_dict, meeting_full, meeting_summary,
                                      nudge_dict)

router = APIRouter(prefix="/api/meetings", tags=["meetings"])


def _detail(db: Session, meeting_id: int) -> dict:
    m = meetings.get_meeting(db, meeting_id)
    previous = meetings.get_meeting(db, m.previous_meeting_id) if m.previous_meeting_id else None
    briefs = db.scalars(select(Brief).where(Brief.meeting_id == m.id).order_by(Brief.id.desc()))
    latest: dict[str, Brief] = {}
    for b in briefs:
        latest.setdefault(b.person_name, b)
    nudges = db.scalars(select(Nudge).where(Nudge.meeting_id == m.id).order_by(Nudge.sent_at.is_not(None), Nudge.id))
    return {
        **meeting_full(m),
        "previous_meeting": meeting_summary(previous) if previous else None,
        "items": [item_dict(i) for i in m.items if i.carried_to_id is None],
        "carried_out_items": [item_dict(i) for i in m.items if i.carried_to_id is not None],
        "health": health.compute_health(db, m),
        "links": [link_dict(l, t) for l, t in ai_features.meeting_links(db, m)],
        "briefs": [brief_dict(b) for b in latest.values()],
        "nudges": [nudge_dict(n) for n in nudges],
        "timeline": meetings.timeline(db, m),
    }


@router.get("")
def list_meetings(db: Session = Depends(get_db)):
    out = []
    for m in meetings.list_meetings(db):
        h = health.compute_health(db, m)
        out.append({**meeting_summary(m), "health": {"score": h["score"], "band": h["band"]}})
    return out


@router.post("", status_code=201)
def create_meeting(body: MeetingIn, db: Session = Depends(get_db)):
    return _detail(db, meetings.create_meeting(db, body).id)


@router.get("/{meeting_id}")
def get_meeting(meeting_id: int, db: Session = Depends(get_db)):
    return _detail(db, meeting_id)


@router.put("/{meeting_id}")
def update_meeting(meeting_id: int, body: MeetingIn, db: Session = Depends(get_db)):
    meetings.update_meeting(db, meeting_id, body)
    return _detail(db, meeting_id)


@router.delete("/{meeting_id}", status_code=204)
def delete_meeting(meeting_id: int, db: Session = Depends(get_db)):
    meetings.delete_meeting(db, meeting_id)


@router.post("/{meeting_id}/status")
def change_status(meeting_id: int, body: StatusChange, db: Session = Depends(get_db)):
    meetings.change_status(db, meeting_id, body.status)
    return _detail(db, meeting_id)


@router.post("/{meeting_id}/carry-over")
def carry_over(meeting_id: int, body: CarryOverIn, db: Session = Depends(get_db)):
    copies = meetings.carry_over(db, meeting_id, body.from_meeting_id)
    return {"carried": len(copies), "meeting": _detail(db, meeting_id)}


@router.post("/{meeting_id}/recap")
def suggest_recap(meeting_id: int, body: RecapRequest, db: Session = Depends(get_db)):
    recap, mode = ai_features.generate_recap(db, meeting_id, body.text)
    return {"recap": recap.model_dump(mode="json"), "ai_mode": mode, "saved": False}


@router.post("/{meeting_id}/recap/accept")
def accept_recap(meeting_id: int, body: RecapAccept, db: Session = Depends(get_db)):
    ai_features.accept_recap(db, meeting_id, body)
    return _detail(db, meeting_id)


@router.post("/{meeting_id}/briefs")
def brief(meeting_id: int, body: BriefRequest, db: Session = Depends(get_db)):
    b, cached = ai_features.get_or_create_brief(db, meeting_id, body.person_name.strip(), body.regenerate)
    return {"brief": brief_dict(b), "cached": cached, "ai_mode": b.generated_by}


@router.post("/{meeting_id}/links/suggest")
def suggest_links(meeting_id: int, db: Session = Depends(get_db)):
    added, mode = ai_features.suggest_links(db, meeting_id)
    return {"added": added, "ai_mode": mode, "meeting": _detail(db, meeting_id)}


@router.get("/{meeting_id}/health")
def get_health(meeting_id: int, db: Session = Depends(get_db)):
    return health.compute_health(db, meetings.get_meeting(db, meeting_id))


@router.post("/{meeting_id}/nudges")
def nudges(meeting_id: int, db: Session = Depends(get_db)):
    created, mode = health.generate_nudges(db, meeting_id)
    return {"nudges": [nudge_dict(n) for n in created], "ai_mode": mode}
