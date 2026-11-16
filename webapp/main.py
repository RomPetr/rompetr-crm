from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError

from webapp.config import ROOT, get_settings
from webapp.db import SessionLocal
from webapp.logging import configure_logging
from webapp.middleware import AuthContextMiddleware, SecurityHeadersMiddleware
from webapp.routers import admin, auth, dashboard, drafts, health, media, public, tickets
from webapp.services.bootstrap import ensure_root_admin

STATIC_DIR = Path(__file__).resolve().parent / "static"
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    settings = get_settings()
    configure_logging()
    for name in ("media", "jobs", "logs", "mail"):
        (ROOT / "var" / name).mkdir(parents=True, exist_ok=True)
    settings.media_path.mkdir(parents=True, exist_ok=True)
    if settings.is_prod and not settings.adm_passw.get_secret_value():
        raise RuntimeError("APP_ENV=prod требует ADM_PASSW")

    db = SessionLocal()
    try:
        ensure_root_admin(db)
    except SQLAlchemyError as exc:
        db.rollback()
        if settings.is_prod:
            raise
        log.warning("admin bootstrap skipped: %s", exc)
    finally:
        db.close()

    worker_stop = None
    worker_thread = None
    if settings.worker_inprocess and settings.app_env != "test":
        from webapp.worker import loop

        worker_stop = threading.Event()
        worker_thread = threading.Thread(
            target=loop,
            args=(worker_stop, f"{settings.worker_id}-inproc"),
            daemon=True,
            name="crm-worker",
        )
        worker_thread.start()
        log.info("in-process worker started")

    try:
        yield
    finally:
        if worker_stop is not None:
            worker_stop.set()
            if worker_thread is not None:
                worker_thread.join(timeout=10)
            log.info("in-process worker stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        docs_url="/docs" if not settings.is_prod else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    application.add_middleware(SecurityHeadersMiddleware)
    application.add_middleware(AuthContextMiddleware)
    application.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    application.include_router(health.router)
    application.include_router(public.router)
    application.include_router(auth.router)
    application.include_router(dashboard.router)
    application.include_router(tickets.router)
    application.include_router(drafts.router)
    application.include_router(media.router)
    application.include_router(admin.router)
    return application


app = create_app()
