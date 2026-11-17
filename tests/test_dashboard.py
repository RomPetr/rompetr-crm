from __future__ import annotations

from webapp.db import SessionLocal
from webapp.models.user import User
from webapp.services.security import hash_password


def csrf(client) -> str:
    client.get("/login")
    return client.cookies.get("csrf_token")


def test_guest_dashboard_counts_are_links(client):
    db = SessionLocal()
    try:
        if not db.query(User).filter(User.login == "dashguest").first():
            db.add(
                User(
                    login="dashguest",
                    email="dashguest@example.com",
                    password_hash=hash_password("dashguest-password-123"),
                    role="guest",
                    status="active",
                )
            )
            db.commit()
    finally:
        db.close()

    token = csrf(client)
    login = client.post(
        "/login",
        data={"csrf_token": token, "username": "dashguest", "password": "dashguest-password-123"},
        follow_redirects=False,
    )
    assert login.status_code == 303

    page = client.get("/dashboard")
    assert page.status_code == 200
    assert 'href="/drafts"' in page.text
    assert 'href="/tickets"' in page.text
    assert "Ваших черновиков" in page.text
    assert "Открытых тикетов" in page.text
