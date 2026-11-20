from __future__ import annotations

from webapp.db import SessionLocal
from webapp.models.system import Job
from webapp.models.user import User
from webapp.services import posts
from webapp.services.security import hash_password


def csrf(client) -> str:
    client.get("/login")
    return client.cookies.get("csrf_token")


def login(client, username: str, password: str) -> str:
    token = csrf(client)
    response = client.post(
        "/login",
        data={"csrf_token": token, "username": username, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return token


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

    token = login(client, "admin", "test-admin-password-12345")

    granted = client.post(
        f"/admin/users/{guest_id}/limits",
        data={
            "csrf_token": token,
            "compose_remaining": "2",
            "image_remaining": "3",
            "publication_remaining": "4",
        },
        follow_redirects=False,
    )
    assert granted.status_code == 303
    assert granted.headers["location"] == "/admin/users?ok=limits"

    db = SessionLocal()
    try:
        guest = db.get(User, guest_id)
        assert guest.guest_compose_limit == 2
        assert guest.guest_image_limit == 3
        assert guest.guest_publication_limit == 4
    finally:
        db.close()

    page = client.get("/admin/users?ok=limits")
    assert page.status_code == 200
    assert "Остаток лимитов обновлён." in page.text
    assert "Использовано: поиск 0 · картинки 0 · публикации 0" in page.text
    assert "Осталось: поиск 2 · картинки 3 · публикации 4" in page.text
    assert "Сохранить лимиты" in page.text


def test_admin_sets_remaining_instead_of_total(client):
    db = SessionLocal()
    try:
        guest = db.query(User).filter(User.login == "remainderguest").first()
        if guest is None:
            guest = User(
                login="remainderguest",
                email="remainderguest@example.com",
                password_hash=hash_password("remainderguest-password-123"),
                role="guest",
                status="active",
            )
            db.add(guest)
            db.commit()
        guest_id = guest.id
        published = posts.create_draft(db, guest, "Remaining limits published")
        published.status = "published"
        draft = posts.create_draft(db, guest, "Remaining limits draft")
        db.add(
            Job(
                public_id="test-remaining-compose",
                type="compose_news",
                status="succeeded",
                payload={},
                idempotency_key="test-remaining-compose",
                created_by=guest.id,
            )
        )
        db.add(
            Job(
                public_id="test-remaining-image",
                type="generate_image",
                status="succeeded",
                payload={},
                idempotency_key="test-remaining-image",
                created_by=guest.id,
            )
        )
        db.commit()
        post_id = draft.id
    finally:
        db.close()

    token = login(client, "admin", "test-admin-password-12345")
    granted = client.post(
        f"/admin/users/{guest_id}/limits",
        data={
            "csrf_token": token,
            "compose_remaining": "3",
            "image_remaining": "2",
            "publication_remaining": "1",
        },
        follow_redirects=False,
    )
    assert granted.status_code == 303

    db = SessionLocal()
    try:
        guest = db.get(User, guest_id)
        assert guest.guest_compose_limit == 4
        assert guest.guest_image_limit == 3
        assert guest.guest_publication_limit == 2
    finally:
        db.close()

    page = client.get("/admin/users?ok=limits")
    assert "Использовано: поиск 1 · картинки 1 · публикации 1" in page.text
    assert "Осталось: поиск 3 · картинки 2 · публикации 1" in page.text

    client.post("/logout", data={"csrf_token": token}, follow_redirects=False)
    login(client, "remainderguest", "remainderguest-password-123")

    page = client.get(f"/drafts/{post_id}")
    assert page.status_code == 200
    assert "Поиск: осталось 3" in page.text
    assert "Картинки: осталось 2" in page.text
    assert "Публикаций: осталось 1" in page.text
