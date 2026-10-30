"""Runs one AI task safely: call -> validate JSON -> retry once -> fall back to rules. Logs every attempt."""
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from app.ai import providers
from app.core.config import get_settings
from app.core.constants import AI_MAX_ATTEMPTS
from app.core.logging import log_event

logger = logging.getLogger("app.ai")
T = TypeVar("T", bound=BaseModel)

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


@dataclass
class AIOutcome(Generic[T]):
    data: T
    mode: str  # "ai" or "basic"


class _Status:
    """Remembers how the last AI call went so the UI can show the 'basic mode' banner."""

    def __init__(self):
        self.last_ok: bool | None = None
        self.last_error: str = ""
        self.last_checked: datetime | None = None

    def record(self, ok: bool, error: str = "") -> None:
        self.last_ok, self.last_error, self.last_checked = ok, error, datetime.utcnow()

    def as_dict(self) -> dict:
        settings = get_settings()
        configured = settings.ai_configured
        mode = "ai" if configured and self.last_ok is not False else "basic"
        reason = "" if mode == "ai" else ("No AI key configured" if not configured else self.last_error)
        return {"configured": configured, "provider": settings.ai_provider.lower() if configured else "none",
                "model": settings.resolved_model if configured else "", "mode": mode, "reason": reason,
                "last_checked": self.last_checked.isoformat() if self.last_checked else None}


ai_status = _Status()


def extract_json(text: str) -> str:
    """Strip code fences and surrounding chatter so only the JSON object is left."""
    text = _FENCE.sub("", text.strip())
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found in AI output")
    return text[start:end + 1]


def run_structured(purpose: str, system: str, user: str, schema: type[T], fallback: Callable[[], T]) -> AIOutcome[T]:
    client = providers.get_ai_client()
    if client is None:
        log_event(logger, "ai_call", "AI not configured, using basic mode", logging.INFO,
                  purpose=purpose, provider="none", outcome="fallback", reason="not_configured")
        return AIOutcome(fallback(), "basic")

    last_error = ""
    for attempt in range(1, AI_MAX_ATTEMPTS + 1):
        start = time.perf_counter()
        base = {"purpose": purpose, "provider": client.provider, "model": client.model,
                "attempt": attempt, "input_chars": len(system) + len(user)}
        try:
            raw, usage = client.complete_json(system, user)
            logger.debug("AI raw output received", extra={"event": "ai_raw_output", **base, "output_chars": len(raw)})
            data = schema.model_validate(json.loads(extract_json(raw)))
            latency = round((time.perf_counter() - start) * 1000)
            log_event(logger, "ai_call", f"AI {purpose} succeeded", logging.INFO,
                      **base, latency_ms=latency, outcome="success", **usage)
            ai_status.record(True)
            return AIOutcome(data, "ai")
        except (ValidationError, ValueError) as exc:  # json.JSONDecodeError is a ValueError
            last_error = f"invalid_output: {type(exc).__name__}"
        except Exception as exc:  # timeout, network, auth, refusal, provider errors
            last_error = f"{type(exc).__name__}"
        latency = round((time.perf_counter() - start) * 1000)
        outcome = "retry" if attempt < AI_MAX_ATTEMPTS else "error"
        log_event(logger, "ai_call", f"AI {purpose} attempt {attempt} failed", logging.WARNING,
                  **base, latency_ms=latency, outcome=outcome, error=last_error)

    log_event(logger, "ai_fallback", f"AI {purpose} unavailable, using basic mode", logging.WARNING,
              purpose=purpose, provider=client.provider, model=client.model, outcome="fallback", error=last_error)
    ai_status.record(False, f"Last AI call failed ({last_error})")
    return AIOutcome(fallback(), "basic")
