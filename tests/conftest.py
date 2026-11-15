from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("APP_SECRET_KEY", "test-secret-key-not-for-prod")
db_path = (ROOT / "var" / "test.sqlite3").as_posix()
os.environ.setdefault("DATABASE_URL", f"sqlite+pysqlite:///{db_path}")
os.environ.setdefault("COOKIE_SECURE", "false")


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from webapp.main import app

    with TestClient(app) as test_client:
        yield test_client
