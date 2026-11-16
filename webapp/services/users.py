from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from webapp.models.support import Ticket, TicketMessage
from webapp.models.user import EmailToken, User
from webapp.services.security import hash_password, new_token, token_hash

LOGIN_RE = re.compile(r"^[a-z0-9_]{3,32}$")
PASSWORD_MIN = 12


def normalize_login(login: str) -> str:
    return login.strip().lower()


def create_user(db: Session, *, login: str, email: str, password: str) -> tuple[User, str]:
    login = normalize_login(login)
    user = User(
        login=login,
        email=email.strip().lower(),
        password_hash=hash_password(password),
        role="guest",
        status="pending",
    )
    db.add(user)
    db.flush()

    token = new_token()
    db.add(
        EmailToken(
            user_id=user.id,
            kind="verify_email",
            token_hash=token_hash(token),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
    )
    db.flush()
    return user, token


def find_by_login_or_email(db: Session, value: str) -> User | None:
    value = value.strip().lower()
    return db.execute(
        select(User).where((User.login == value) | (User.email == value))
    ).scalar_one_or_none()


def consume_token(db: Session, token: str, kind: str) -> User | None:
    row = db.execute(
        select(EmailToken).where(
            EmailToken.token_hash == token_hash(token),
            EmailToken.kind == kind,
            EmailToken.used_at.is_(None),
            EmailToken.expires_at > datetime.now(timezone.utc),
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    user = db.get(User, row.user_id)
    if user is None:
        return None
    row.used_at = datetime.now(timezone.utc)
    db.flush()
    return user


def activate_user(db: Session, user: User) -> Ticket | None:
    user.status = "active"
    user.email_verified_at = datetime.now(timezone.utc)
    db.flush()

    existing = db.execute(
        select(Ticket).where(
            Ticket.user_id == user.id, Ticket.kind == "access_request", Ticket.status != "closed"
        )
    ).scalar_one_or_none()
    if existing:
        return existing

    ticket = Ticket(
        user_id=user.id,
        kind="access_request",
        subject=f"Запрос доступа: {user.login}",
        status="open",
        priority=1,
    )
    db.add(ticket)
    db.flush()
    db.add(
        TicketMessage(
            ticket_id=ticket.id,
            author_id=user.id,
            body="Пользователь подтвердил e-mail и запрашивает доступ к публикации.",
        )
    )
    db.flush()
    return ticket


def issue_reset_token(db: Session, user: User) -> str:
    token = new_token()
    db.add(
        EmailToken(
            user_id=user.id,
            kind="reset_password",
            token_hash=token_hash(token),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
    )
    db.flush()
    return token


def set_password(db: Session, user: User, password: str) -> None:
    user.password_hash = hash_password(password)
    db.flush()
