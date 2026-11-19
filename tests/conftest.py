from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
(ROOT / "var").mkdir(parents=True, exist_ok=True)
db_path = (ROOT / "var" / "test.sqlite3").as_posix()

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("APP_SECRET_KEY", "test-secret-key-not-for-prod")
os.environ.setdefault("DATABASE_URL", f"sqlite+pysqlite:///{db_path}")
os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault("ADM_PASSW", "test-admin-password-12345")
os.environ.setdefault("ADMIN_EMAIL", "admin@example.com")
os.environ.setdefault("EMAIL_MODE", "dev")
os.environ.setdefault("WORKER_INPROCESS", "false")


@pytest.fixture(scope="session", autouse=True)
def database():
    from webapp.db import Base, engine
    from webapp.models import content, support, system, user  # noqa: F401

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    from webapp.db import SessionLocal
    from webapp.services.bootstrap import ensure_root_admin

    db = SessionLocal()
    try:
        ensure_root_admin(db)
    finally:
        db.close()
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture(scope="session")
def client(database):
    from fastapi.testclient import TestClient

    from webapp.main import app

    with TestClient(app) as test_client:
        yield test_client


def csrf(client) -> str:
    client.get("/login")
    return client.cookies.get("csrf_token")
