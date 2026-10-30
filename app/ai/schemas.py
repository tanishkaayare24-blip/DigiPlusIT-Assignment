"""Pydantic models that every AI response must pass before the app uses it."""
from datetime import date

from pydantic import BaseModel, Field, field_validator

from app.core.constants import PRIORITIES


def _strings(values) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(v).strip() for v in values if str(v).strip()]


class RecapItemOut(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    owner: str = ""
    due_date: date | None = None
    priority: str = "medium"
    confidence: float = 0.5

    @field_validator("owner", mode="before")
    @classmethod
    def owner_str(cls, v) -> str:
        return "" if v is None or str(v).lower() in {"unknown", "none", "null", "tbd"} else str(v).strip()

    @field_validator("due_date", mode="before")
    @classmethod
    def lenient_date(cls, v):
        if not v:
            return None
        try:
            return date.fromisoformat(str(v)[:10])
        except ValueError:
            return None

    @field_validator("priority", mode="before")
    @classmethod
    def norm_priority(cls, v) -> str:
        v = str(v or "").lower().strip()
        return v if v in PRIORITIES else "medium"

    @field_validator("confidence", mode="before")
    @classmethod
    def clamp(cls, v) -> float:
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return 0.5


class RecapOut(BaseModel):
    summary: str = Field(min_length=1, max_length=5000)
    decisions: list[str] = Field(default_factory=list)
    action_items: list[RecapItemOut] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)

    @field_validator("decisions", "open_questions", "risks", mode="before")
    @classmethod
    def clean_lists(cls, v) -> list[str]:
        return _strings(v)


class BriefOut(BaseModel):
    headline: str = Field(min_length=1, max_length=300)
    what_happened: str = Field(min_length=1, max_length=3000)
    decisions_affecting_you: list[str] = Field(default_factory=list)
    your_items: list[str] = Field(default_factory=list)
    overdue: list[str] = Field(default_factory=list)
    do_first: list[str] = Field(default_factory=list)

    @field_validator("decisions_affecting_you", "your_items", "overdue", "do_first", mode="before")
    @classmethod
    def clean_lists(cls, v) -> list[str]:
        return _strings(v)


class LinkPick(BaseModel):
    candidate_id: str
    reason: str = Field(min_length=3, max_length=300)


class LinksOut(BaseModel):
    links: list[LinkPick] = Field(default_factory=list)


class NudgeText(BaseModel):
    key: str
    message: str = Field(min_length=10, max_length=600)


class NudgesOut(BaseModel):
    nudges: list[NudgeText] = Field(default_factory=list)
