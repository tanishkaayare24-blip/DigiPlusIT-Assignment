"""Request-ID middleware: one UUID per request, attached to every log line and response."""
import logging
import re
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.logging import log_event, request_id_var

logger = logging.getLogger("app.http")
_VALID_ID = re.compile(r"^[A-Za-z0-9\-_.]{1,64}$")
_QUIET_PREFIXES = ("/static", "/health", "/favicon")


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get("X-Request-ID", "")
        request_id = incoming if _VALID_ID.match(incoming) else str(uuid.uuid4())
        token = request_id_var.set(request_id)
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 1)
            quiet = request.url.path.startswith(_QUIET_PREFIXES) or request.url.path == "/"
            level = logging.DEBUG if quiet and status < 400 else logging.INFO
            log_event(logger, "http_request", f"{request.method} {request.url.path} -> {status}", level,
                      method=request.method, path=request.url.path, status=status, duration_ms=duration_ms)
            request_id_var.reset(token)
