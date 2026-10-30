"""JSON logging with request IDs and secret redaction."""
import json
import logging
import re
from contextvars import ContextVar
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}

_SECRET_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?i)((?:api[_-]?key|x-api-key|authorization|token|secret)[\"']?\s*[:=]\s*[\"']?)[^\s\"',}]+"),
]
REDACTED = "[REDACTED]"


def redact(text: str, extra_secrets: tuple[str, ...] = ()) -> str:
    for secret in extra_secrets:
        if secret and len(secret) >= 6:
            text = text.replace(secret, REDACTED)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda m: (m.group(1) if m.groups() else "") + REDACTED, text)
    return text


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line. Extra fields passed via `extra=` become top-level keys."""

    def __init__(self, secrets: tuple[str, ...] = ()):
        super().__init__()
        self.secrets = secrets

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
            "event": getattr(record, "event", None),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            payload["exc_message"] = str(record.exc_info[1])
        return redact(json.dumps(payload, default=str), self.secrets)


def setup_logging(level: str, log_dir: str, secrets: tuple[str, ...] = ()) -> None:
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    formatter = JsonFormatter(secrets)
    request_filter = RequestIdFilter()

    file_handler = RotatingFileHandler(Path(log_dir) / "app.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    console_handler = logging.StreamHandler()
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    for handler in (file_handler, console_handler):
        handler.setFormatter(formatter)
        handler.addFilter(request_filter)
        root.addHandler(handler)
    root.setLevel(level.upper())
    # Keep third-party noise down; our own middleware logs every request.
    for noisy in ("uvicorn.access", "httpx", "httpcore", "anthropic", "google_genai", "httpx2"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def log_event(logger: logging.Logger, event: str, message: str | None = None, level: int = logging.INFO, **context) -> None:
    """Log a named business event with structured context fields."""
    logger.log(level, message or event, extra={"event": event, **context})
