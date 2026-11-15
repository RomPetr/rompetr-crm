from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from webapp.config import ROOT, get_settings
from webapp.logging import configure_logging
from webapp.middleware import SecurityHeadersMiddleware
from webapp.routers import health, public

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    settings = get_settings()
    configure_logging()
    for name in ("media", "jobs", "logs", "mail"):
        (ROOT / "var" / name).mkdir(parents=True, exist_ok=True)
    settings.media_path.mkdir(parents=True, exist_ok=True)
    if settings.is_prod and not settings.adm_passw.get_secret_value():
        raise RuntimeError("APP_ENV=prod требует ADM_PASSW")
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        docs_url="/docs" if not settings.is_prod else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    application.add_middleware(SecurityHeadersMiddleware)
    application.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    application.include_router(health.router)
    application.include_router(public.router)
    return application


app = create_app()
