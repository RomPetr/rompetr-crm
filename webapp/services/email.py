from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from webapp.config import ROOT, get_settings
from webapp.models.system import EmailOutbox

log = logging.getLogger(__name__)


def enqueue_email(db: Session, to_email: str, subject: str, body_text: str) -> EmailOutbox:
    email = EmailOutbox(to_email=to_email, subject=subject, body_text=body_text)
    db.add(email)
    db.flush()

    settings = get_settings()
    if settings.email_mode in {"dev", "file"}:
        mail_dir = ROOT / "var" / "mail"
        mail_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        path = mail_dir / f"{stamp}-{email.id}.txt"
        path.write_text(
            f"To: {to_email}\nSubject: {subject}\n\n{body_text}\n",
            encoding="utf-8",
        )
        email.status = "sent"
        email.sent_at = datetime.now(timezone.utc)
        log.info("email_dev_written path=%s to=%s", path, to_email)
    return email


def verification_link(token: str) -> str:
    return f"{get_settings().app_base_url.rstrip('/')}/verify?token={token}"


def reset_link(token: str) -> str:
    return f"{get_settings().app_base_url.rstrip('/')}/reset-password?token={token}"


def mail_body(title: str, intro: str, link: str) -> str:
    return f"{title}\n\n{intro}\n\n{link}\n\nЕсли вы не запрашивали это письмо, просто проигнорируйте его."


__all__ = ["enqueue_email", "verification_link", "reset_link", "mail_body", "Path"]
