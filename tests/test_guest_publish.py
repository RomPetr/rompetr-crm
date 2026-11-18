from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from webapp.db import SessionLocal
from webapp.models.content import Post
from webapp.models.user import User
from webapp.services import posts
from webapp.services.security import hash_password


def csrf(client) -> str:
    client.get("/login")
    return client.cookies.get("csrf_token")


def make_guest(db):
    guest = db.query(User).filter(User.login == "pubguest").first()
    if guest is None:
        guest = User(
            login="pubguest",
            email="pubguest@example.com",
            password_hash=hash_password("pubguest-password-123"),
            role="guest",
            status="active",
        )
        db.add(guest)
        db.commit()
    return guest


def make_post(db, guest: User, title: str, status: str = "approved") -> Post:
    post = posts.create_draft(db, guest, title)
    post.status = status
    db.commit()
    return post


def test_guest_can_publish_one_approved_post(monkeypatch, client):
    db = SessionLocal()
    try:
        guest = make_guest(db)
        guest_id = guest.id
        unapproved = make_post(db, guest, "Guest unapproved", status="draft")
        first = make_post(db, guest, "Guest first approved")
        first_id = first.id
        unapproved_id = unapproved.id
    finally:
        db.close()

    def fake_publish(db, post, actor):
        post.status = "published"
        post.published_at = datetime.now(timezone.utc)
        db.flush()
        return [SimpleNamespace(platform="telegram", status="published")]

    monkeypatch.setattr("webapp.routers.drafts.publish_service.publish_post", fake_publish)

    token = csrf(client)
    login = client.post(
        "/login",
        data={"csrf_token": token, "username": "pubguest", "password": "pubguest-password-123"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    token = csrf(client)

    denied = client.post(
        f"/drafts/{unapproved_id}/publish",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert denied.status_code == 400
    assert "одобрения" in denied.text

    published = client.post(
        f"/drafts/{first_id}/publish",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert published.status_code == 303
    assert published.headers["location"] == f"/drafts/{first_id}?ok=published"

    db = SessionLocal()
    try:
        assert db.get(Post, first_id).status == "published"
        second = make_post(db, db.get(User, guest_id), "Guest second approved")
        second_id = second.id
    finally:
        db.close()

    too_many = client.post(
        f"/drafts/{second_id}/publish",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert too_many.status_code == 400
    assert "лимит публикаций" in too_many.text.lower()
