"""Request bodies for the API (Pydantic v2). Responses are plain dicts built in services/serializers.py."""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.constants import CLOSED_ITEM_STATUSES

MeetingType = Literal["meeting", "handover"]
MeetingStatus = Literal["draft", "scheduled", "completed", "archived"]
Attendance = Literal["yes", "no", "no_response"]
ItemStatus = Literal["open", "in_progress", "blocked", "done", "dropped"]
Priority = Literal["low", "medium", "high"]


def _clean_list(values: list[str]) -> list[str]:
    return [v.strip() for v in values if v and v.strip()]


class ParticipantIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(default="", max_length=200)
    role: str = Field(default="", max_length=120)
    attended: Attendance = "no_response"

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str) -> str:
        v = v.strip()
        if v and ("@" not in v or " " in v):
            raise ValueError("must be a valid email address")
        return v


class MeetingIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    type: MeetingType = "meeting"
    agenda: str = Field(default="", max_length=5000)
    raw_notes: str = Field(default="", max_length=50000)
    decisions: list[str] = Field(default_factory=list, max_length=50)
    scheduled_at: datetime | None = None
    previous_meeting_id: int | None = None
    participants: list[ParticipantIn] = Field(default_factory=list, max_length=50)

    @field_validator("decisions")
    @classmethod
    def clean_decisions(cls, v: list[str]) -> list[str]:
        return _clean_list(v)

    @field_validator("title")
    @classmethod
    def strip_title(cls, v: str) -> str:
        if len(v.strip()) < 3:
            raise ValueError("title must have at least 3 characters")
        return v.strip()


class StatusChange(BaseModel):
    status: MeetingStatus


class CarryOverIn(BaseModel):
    from_meeting_id: int | None = None


class ItemIn(BaseModel):
    meeting_id: int
    title: str = Field(min_length=3, max_length=300)
    owner: str = Field(default="", max_length=120)
    due_date: date | None = None
    priority: Priority = "medium"
    ai_suggested: bool = False


class ItemUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=300)
    owner: str | None = Field(default=None, max_length=120)
    due_date: date | None = None
    priority: Priority | None = None
    status: ItemStatus | None = None
    outcome: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def outcome_required_when_closing(self):
        if self.status in CLOSED_ITEM_STATUSES and not (self.outcome or "").strip():
            raise ValueError(f"An outcome is required when marking an item as '{self.status}'.")
        return self


class KBDocIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    content: str = Field(min_length=10, max_length=20000)
    tags: list[str] = Field(default_factory=list, max_length=15)

    @field_validator("tags")
    @classmethod
    def norm_tags(cls, v: list[str]) -> list[str]:
        return sorted({t.strip().lower() for t in v if t.strip()})


class RecapRequest(BaseModel):
    text: str = Field(min_length=20, max_length=50000)


class RecapItemIn(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    owner: str = ""
    due_date: date | None = None
    priority: Priority = "medium"


class RecapAccept(BaseModel):
    summary: str = Field(default="", max_length=5000)
    decisions: list[str] = Field(default_factory=list)
    action_items: list[RecapItemIn] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    source_text: str = Field(default="", max_length=50000)

    @field_validator("decisions", "open_questions", "risks")
    @classmethod
    def clean(cls, v: list[str]) -> list[str]:
        return _clean_list(v)


class BriefRequest(BaseModel):
    person_name: str = Field(min_length=1, max_length=120)
    regenerate: bool = False
