from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from webapp.config import get_settings
from webapp.models.system import AppSetting
from webapp.models.user import User
from webapp.services.security import hash_password, verify_password

log = logging.getLogger(__name__)


def ensure_root_admin(db: Session) -> None:
    settings = get_settings()
    admin = db.get(User, 0)

    if admin is not None:
        raw = settings.adm_passw.get_secret_value()
        if raw and not verify_password(admin.password_hash, raw):
            _set_flag(db, "admin_env_mismatch", {"at": datetime.now(timezone.utc).isoformat()})
            log.warning("ADM_PASSW differs from stored admin password; env change ignored")
        return

    if not settings.admin_bootstrap:
        return

    password = settings.adm_passw.get_secret_value()
    if len(password) < 16:
        raise RuntimeError("ADM_PASSW должен быть не короче 16 символов")

    email = settings.admin_email or "admin@rompetr.ru"
    admin = User(
        id=0,
        login=settings.admin_login,
        email=email,
        password_hash=hash_password(password),
        role="admin",
        status="active",
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(admin)
    db.flush()

    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(
            text(
                "SELECT setval(pg_get_serial_sequence('users','id'), "
                "GREATEST((SELECT COALESCE(MAX(id), 1) FROM users), 1))"
            )
        )
    _set_flag(db, "admin_bootstrapped_at", {"at": datetime.now(timezone.utc).isoformat()})
    db.commit()
    log.info("admin id=0 bootstrapped login=%s", admin.login)


def _set_flag(db: Session, key: str, value: dict) -> None:
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=value))
    else:
        row.value = value
    db.flush()
