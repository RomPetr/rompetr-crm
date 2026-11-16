from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from webapp.db import get_db
from webapp.models.user import User

SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


def current_user(request: Request) -> User | None:
    return getattr(request.state, "user", None)


def require_user(request: Request) -> User:
    user = current_user(request)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"}
        )
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ запрещён")
    return user


async def csrf_protect(request: Request) -> None:
    if request.method in SAFE_METHODS:
        return
    import secrets

    form = await request.form()
    provided = form.get("csrf_token") or request.headers.get("x-csrf-token")
    expected = request.cookies.get("csrf_token")
    if not provided or not expected or not secrets.compare_digest(str(provided), expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token invalid")


def db_session(db: Session = Depends(get_db)) -> Session:
    return db
