from __future__ import annotations

from webapp.db import SessionLocal
from webapp.models.user import User
from webapp.services.security import hash_password


def csrf(client) -> str:
    client.get("/login")
    return client.cookies.get("csrf_token")


def test_admin_can_grant_guest_limits(client):
    db = SessionLocal()
    try:
        guest = db.query(User).filter(User.login == "grantguest").first()
        if guest is None:
            guest = User(
                login="grantguest",
                email="grantguest@example.com",
                password_hash=hash_password("grantguest-password-123"),
                role="guest",
                status="active",
            )
            db.add(guest)
            db.commit()
        guest_id = guest.id
    finally:
        db.close()

    token = csrf(client)
    login = client.post(
        "/login",
        data={"csrf_token": token, "username": "admin", "password": "test-admin-password-12345"},
        follow_redirects=False,
    )
    assert login.status_code == 303

    for kind in ("compose", "image"):
        granted = client.post(
            f"/admin/users/{guest_id}/limits/{kind}",
            data={"csrf_token": token},
            follow_redirects=False,
        )
        assert granted.status_code == 303
        assert granted.headers["location"] == "/admin/users?ok=limits"

    db = SessionLocal()
    try:
        guest = db.get(User, guest_id)
        assert guest.guest_compose_limit == 2
        assert guest.guest_image_limit == 3
    finally:
        db.close()

    page = client.get("/admin/users?ok=limits")
    assert page.status_code == 200
    assert "Гостевые лимиты обновлены." in page.text
    assert "Поиск: 0/2" in page.text
    assert "Картинки: 0/3" in page.text
    assert "+1 поиск" in page.text
    assert "+1 картинка" in page.text
