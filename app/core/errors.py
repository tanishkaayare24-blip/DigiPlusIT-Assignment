"""One error shape for the whole API: {error, detail, request_id}."""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import log_event, request_id_var

logger = logging.getLogger("app.errors")


class AppError(Exception):
    def __init__(self, status_code: int, error: str, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.error = error
        self.detail = detail


def not_found(what: str, obj_id: int) -> AppError:
    return AppError(404, "not_found", f"{what} {obj_id} was not found.")


def _body(error: str, detail) -> dict:
    return {"error": error, "detail": detail, "request_id": request_id_var.get()}


def _format_validation(exc: RequestValidationError) -> list[dict]:
    out = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", []) if p != "body")
        out.append({"field": loc, "message": err.get("msg", "Invalid value")})
    return out


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        log_event(logger, "app_error", exc.detail, logging.WARNING,
                  route=request.url.path, status=exc.status_code, error=exc.error)
        return JSONResponse(status_code=exc.status_code, content=_body(exc.error, exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        details = _format_validation(exc)
        log_event(logger, "validation_error", "Request validation failed", logging.WARNING,
                  route=request.url.path, fields=[d["field"] for d in details])
        return JSONResponse(status_code=422, content=_body("validation_error", details))

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(request: Request, exc: StarletteHTTPException):
        return JSONResponse(status_code=exc.status_code, content=_body("http_error", str(exc.detail)))

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        logger.error("Unhandled error", exc_info=exc,
                     extra={"event": "unhandled_error", "route": request.url.path, "exc_type": type(exc).__name__})
        return JSONResponse(status_code=500, content=_body("internal_error", "Something went wrong. Please try again."))
