from __future__ import annotations

import re
from pathlib import Path

from webapp.db import SessionLocal
from webapp.models.user import User
from webapp.services.security import hash_password

ROOT = Path(__file__).resolve().parent.parent


def csrf(client) -> str:
    client.get("/login")
    return client.cookies.get("csrf_token")


def make_user(login: str, status: str, password: str = "extra-password-123") -> User:
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.login == login).first()
        if existing:
            return existing
        user = User(
            login=login,
            email=f"{login}@example.com",
            password_hash=hash_password(password),
            role="user",
            status=status,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def latest_mail() -> str:
    files = sorted((ROOT / "var" / "mail").glob("*.txt"), key=lambda p: p.stat().st_mtime)
    assert files
    return files[-1].read_text(encoding="utf-8")


def test_login_rejects_pending_and_blocked(client):
    make_user("pendinguser", "pending", "pending-password-123")
    token = csrf(client)
    response = client.post(
        "/login",
        data={"csrf_token": token, "username": "pendinguser", "password": "pending-password-123"},
        follow_redirects=False,
    )
    assert response.status_code == 403
    assert "Подтвердите e-mail" in response.text

    make_user("blockeduser", "blocked", "blocked-password-123")
    token = csrf(client)
    response = client.post(
        "/login",
        data={"csrf_token": token, "username": "blockeduser", "password": "blocked-password-123"},
        follow_redirects=False,
    )
    assert response.status_code == 403


def test_wrong_password_and_reset_flow(client):
    make_user("resetuser", "active", "old-password-1234")
    token = csrf(client)
    wrong = client.post(
        "/login",
        data={"csrf_token": token, "username": "resetuser", "password": "wrong-password"},
        follow_redirects=False,
    )
    assert wrong.status_code == 400
    assert "Неверный логин или пароль" in wrong.text

    token = csrf(client)
    forgot = client.post(
        "/forgot-password",
        data={"csrf_token": token, "email": "resetuser@example.com"},
        follow_redirects=False,
    )
    assert forgot.status_code == 200
    assert "Если аккаунт" in forgot.text

    mail = latest_mail()
    match = re.search(r"/reset-password\?token=([A-Za-z0-9_-]+)", mail)
    assert match, mail

    bad = client.post(
        "/reset-password",
        data={
            "csrf_token": token,
            "token": "invalid-token",
            "password": "new-password-1234",
            "password_confirm": "new-password-1234",
        },
        follow_redirects=False,
    )
    assert bad.status_code == 400

    reset = client.post(
        "/reset-password",
        data={
            "csrf_token": token,
            "token": match.group(1),
            "password": "new-password-1234",
            "password_confirm": "new-password-1234",
        },
        follow_redirects=False,
    )
    assert reset.status_code == 303

    token = csrf(client)
    login = client.post(
        "/login",
        data={"csrf_token": token, "username": "resetuser", "password": "new-password-1234"},
        follow_redirects=False,
    )
    assert login.status_code == 303

    logout = client.post("/logout", data={"csrf_token": token}, follow_redirects=False)
    assert logout.status_code == 303


def test_invalid_verify_token_and_register_validation(client):
    page = client.get("/verify?token=nope")
    assert page.status_code == 200
    assert "недействительна" in page.text

    token = csrf(client)
    short = client.post(
        "/register",
        data={
            "csrf_token": token,
            "login": "x",
            "email": "bad-email",
            "password": "short",
            "password_confirm": "other",
        },
        follow_redirects=False,
    )
    assert short.status_code == 400
    assert "Логин" in short.text
    assert "Пароли не совпадают" in short.text
