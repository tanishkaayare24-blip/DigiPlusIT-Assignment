"""ContextRelay entry point: `uvicorn app.main:app`."""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.core.db import SessionLocal, init_db
from app.core.errors import register_error_handlers
from app.core.logging import log_event, setup_logging
from app.core.middleware import RequestIdMiddleware
from app.routers import meetings, workspace
from app.services.seed import seed_if_empty

STATIC_DIR = Path(__file__).parent / "static"
settings = get_settings()
setup_logging(settings.log_level, settings.log_dir, secrets=(settings.ai_api_key,))
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    if settings.seed_on_startup:
        with SessionLocal() as db:
            seed_if_empty(db)
    log_event(logger, "app_started", "ContextRelay started", ai_provider=settings.ai_provider,
              ai_model=settings.resolved_model or None, ai_configured=settings.ai_configured)
    yield


app = FastAPI(title="ContextRelay", version="1.0.0", lifespan=lifespan)
app.add_middleware(RequestIdMiddleware)
register_error_handlers(app)
app.include_router(meetings.router)
app.include_router(workspace.router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")
