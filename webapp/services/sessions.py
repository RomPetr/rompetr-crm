from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from webapp.config import get_settings
from webapp.models.user import User, UserSession
from webapp.services.security import new_token, token_hash


def create_session(db: Session, user: User, *, ip: str | None, user_agent: str | None) -> str:
    settings = get_settings()
    token = new_token()
    now = datetime.now(timezone.utc)
    session = UserSession(
        id=str(uuid.uuid4()),
        user_id=user.id,
        token_hash=token_hash(token),
        csrf_secret=new_token(),
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(days=settings.session_ttl_days),
        ip=ip,
        user_agent=(user_agent or "")[:1000] or None,
    )
    db.add(session)
    db.flush()
    return token


def user_for_token(db: Session, token: str) -> tuple[User, UserSession] | None:
    digest = token_hash(token)
    row = db.execute(
        select(UserSession, User)
        .join(User, User.id == UserSession.user_id)
        .where(
            UserSession.token_hash == digest,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > datetime.now(timezone.utc),
            User.status == "active",
        )
    ).first()
    if not row:
        return None
    session, user = row
    return user, session


def touch_session(db: Session, session: UserSession) -> None:
    now = datetime.now(timezone.utc)
    last_seen = session.last_seen_at
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    if (now - last_seen).total_seconds() > 60:
        session.last_seen_at = now
        db.flush()


def revoke_session(db: Session, session: UserSession) -> None:
    session.revoked_at = datetime.now(timezone.utc)
    db.flush()


def revoke_user_sessions(db: Session, user_id: int, *, except_id: str | None = None) -> None:
    stmt = (
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
    if except_id:
        stmt = stmt.where(UserSession.id != except_id)
    db.execute(stmt)
