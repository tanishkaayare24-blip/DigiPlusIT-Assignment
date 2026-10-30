"""Database tables."""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def utcnow() -> datetime:
    return datetime.utcnow().replace(microsecond=0)


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(20), default="meeting")
    status: Mapped[str] = mapped_column(String(20), default="draft")
    agenda: Mapped[str] = mapped_column(Text, default="")
    raw_notes: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    decisions: Mapped[list] = mapped_column(JSON, default=list)
    open_questions: Mapped[list] = mapped_column(JSON, default=list)
    risks: Mapped[list] = mapped_column(JSON, default=list)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    previous_meeting_id: Mapped[int | None] = mapped_column(ForeignKey("meetings.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    participants: Mapped[list["Participant"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan", order_by="Participant.id")
    items: Mapped[list["ActionItem"]] = relationship(back_populates="meeting", order_by="ActionItem.id")


class Participant(Base):
    __tablename__ = "participants"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200), default="")
    role: Mapped[str] = mapped_column(String(120), default="")
    attended: Mapped[str] = mapped_column(String(20), default="no_response")

    meeting: Mapped[Meeting] = relationship(back_populates="participants")


class ActionItem(Base):
    __tablename__ = "action_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id"))
    title: Mapped[str] = mapped_column(String(300))
    owner: Mapped[str] = mapped_column(String(120), default="")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open")
    priority: Mapped[str] = mapped_column(String(10), default="medium")
    outcome: Mapped[str] = mapped_column(Text, default="")
    ai_suggested: Mapped[bool] = mapped_column(Boolean, default=False)
    # Carry-forward chain: origin = first item in the chain, parent = the item this was copied from.
    origin_item_id: Mapped[int | None] = mapped_column(ForeignKey("action_items.id"), nullable=True)
    parent_item_id: Mapped[int | None] = mapped_column(ForeignKey("action_items.id"), nullable=True)
    carried_to_id: Mapped[int | None] = mapped_column(ForeignKey("action_items.id"), nullable=True)
    carry_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    meeting: Mapped[Meeting] = relationship(back_populates="items")

    @property
    def chain_id(self) -> int:
        return self.origin_item_id or self.id


class ItemEvent(Base):
    __tablename__ = "item_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("action_items.id"))
    chain_id: Mapped[int] = mapped_column(Integer, index=True)
    meeting_id: Mapped[int | None] = mapped_column(ForeignKey("meetings.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(40))
    from_value: Mapped[str] = mapped_column(String(300), default="")
    to_value: Mapped[str] = mapped_column(String(300), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class MeetingEvent(Base):
    __tablename__ = "meeting_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id"))
    event_type: Mapped[str] = mapped_column(String(40))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class KBDoc(Base):
    __tablename__ = "kb_docs"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Link(Base):
    """A link from a meeting (optionally one of its items) to a KB doc or a past meeting."""
    __tablename__ = "links"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id"))
    item_id: Mapped[int | None] = mapped_column(ForeignKey("action_items.id"), nullable=True)
    doc_id: Mapped[int | None] = mapped_column(ForeignKey("kb_docs.id"), nullable=True)
    target_meeting_id: Mapped[int | None] = mapped_column(ForeignKey("meetings.id"), nullable=True)
    reason: Mapped[str] = mapped_column(String(300), default="")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(String(20), default="ai")  # ai | basic | manual | seed
    removed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Brief(Base):
    __tablename__ = "briefs"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id"))
    person_name: Mapped[str] = mapped_column(String(120))
    content: Mapped[dict] = mapped_column(JSON)
    generated_by: Mapped[str] = mapped_column(String(20))  # ai | basic
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Nudge(Base):
    __tablename__ = "nudges"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id"))
    item_id: Mapped[int | None] = mapped_column(ForeignKey("action_items.id"), nullable=True)
    recipient: Mapped[str] = mapped_column(String(120))
    reason_code: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    generated_by: Mapped[str] = mapped_column(String(20))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
