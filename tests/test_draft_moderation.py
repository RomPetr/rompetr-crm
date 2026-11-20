from __future__ import annotations

from datetime import datetime, timezone

from webapp.db import SessionLocal
from webapp.models.content import Post
from webapp.models.user import User
from webapp.services import posts
from webapp.services.security import hash_password


def csrf(client) -> str:
    client.get("/login")
    return client.cookies.get("csrf_token")


def make_pending(db, title: str):
    admin = db.get(User, 0)
    post = posts.create_draft(db, admin, title)
    post.status = "pending_review"
    db.commit()
    return post


def login_admin(client) -> str:
    token = csrf(client)
    response = client.post(
        "/login",
        data={"csrf_token": token, "username": "admin", "password": "test-admin-password-12345"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return token


def test_admin_can_approve_from_draft_page(client):
    db = SessionLocal()
    try:
        post = make_pending(db, "Approve from draft")
        post_id = post.id
    finally:
        db.close()

    token = login_admin(client)
    page = client.get(f"/drafts/{post_id}")
    assert page.status_code == 200
    assert "Модерация" in page.text
    assert "Одобрить" in page.text
    assert "Отклонить" in page.text
    assert 'name="reason"' in page.text

    approved = client.post(
        f"/drafts/{post_id}/approve",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert approved.status_code == 303
    assert approved.headers["location"] == f"/drafts/{post_id}?ok=approved"

    db = SessionLocal()
    try:
        post = db.get(Post, post_id)
        assert post.status == "approved"
        assert post.approved_by == 0
    finally:
        db.close()


def test_published_post_shows_moderation_passed(client):
    db = SessionLocal()
    try:
        post = make_pending(db, "Published moderation label")
        post.status = "published"
        post.approved_by = 0
        post.approved_at = datetime.now(timezone.utc)
        post.rejection_reason = None
        db.commit()
        post_id = post.id
    finally:
        db.close()

    login_admin(client)
    page = client.get(f"/drafts/{post_id}")
    assert page.status_code == 200
    assert "Модерация пройдена" in page.text
    assert "Модерация: отклонено" not in page.text
    assert 'class="button published"' in page.text
    assert "Поиск: 0 · лимита нет" in page.text
    assert "Картинки: 0 · лимита нет" in page.text
    assert "Публикаций: 0 · лимита нет" in page.text


def test_admin_can_reject_from_draft_page_with_reason(client):
    db = SessionLocal()
    try:
        post = make_pending(db, "Reject from draft")
        post_id = post.id
    finally:
        db.close()

    token = login_admin(client)
    rejected = client.post(
        f"/drafts/{post_id}/reject",
        data={"csrf_token": token, "reason": "Не хватает фактов и источника"},
        follow_redirects=False,
    )
    assert rejected.status_code == 303
    assert rejected.headers["location"] == f"/drafts/{post_id}?ok=rejected"

    db = SessionLocal()
    try:
        post = db.get(Post, post_id)
        assert post.status == "rejected"
        assert post.rejection_reason == "Не хватает фактов и источника"
    finally:
        db.close()


def test_submitted_flash_updates_after_approval(client):
    db = SessionLocal()
    try:
        user = User(
            login="flashguest",
            email="flashguest@example.com",
            password_hash=hash_password("flashguest-password-123"),
            role="guest",
            status="active",
        )
        db.add(user)
        db.commit()
        post = posts.create_draft(db, user, "Flash message after approval")
        post.status = "pending_review"
        db.commit()
        post_id = post.id
    finally:
        db.close()

    token = csrf(client)
    login = client.post(
        "/login",
        data={
            "csrf_token": token,
            "username": "flashguest",
            "password": "flashguest-password-123",
        },
        follow_redirects=False,
    )
    assert login.status_code == 303

    pending = client.get(f"/drafts/{post_id}?ok=submitted")
    assert "Отправлено на проверку администратору." in pending.text

    db = SessionLocal()
    try:
        post = db.get(Post, post_id)
        post.status = "approved"
        post.approved_by = 0
        post.approved_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()

    approved = client.get(f"/drafts/{post_id}?ok=submitted")
    assert "Подтверждено администратором." in approved.text
    assert "Отправлено на проверку администратору." not in approved.text
