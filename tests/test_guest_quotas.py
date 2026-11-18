from __future__ import annotations

import re

from webapp.db import SessionLocal
from webapp.models.content import Post
from webapp.models.system import Job
from webapp.models.user import User
from webapp.services.security import hash_password


def csrf(client) -> str:
    client.get("/login")
    return client.cookies.get("csrf_token")


def guest_client(client):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.login == "quotaguest").first()
        if user is None:
            user = User(
                login="quotaguest",
                email="quotaguest@example.com",
                password_hash=hash_password("quotaguest-password-123"),
                role="guest",
                status="active",
            )
            db.add(user)
            db.commit()
        user_id = user.id
    finally:
        db.close()

    token = csrf(client)
    login = client.post(
        "/login",
        data={"csrf_token": token, "username": "quotaguest", "password": "quotaguest-password-123"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    return user_id


def test_guest_has_one_search_and_two_images(client):
    guest_client(client)
    token = csrf(client)
    created = client.post(
        "/drafts/new",
        data={"csrf_token": token, "title": "Проверка гостевых квот"},
        follow_redirects=False,
    )
    assert created.status_code == 303
    post_id = int(created.headers["location"].rstrip("/").split("/")[-1])

    db = SessionLocal()
    try:
        post = db.get(Post, post_id)
        post.image_enabled = True
        post.image_prompt = "Cinematic 3D illustration of a newsroom desk, dark fintech style."
        db.commit()
    finally:
        db.close()

    page = client.get(f"/drafts/{post_id}")
    assert "Сгенерировать новость" in page.text
    assert "Поиск: 0/1" in page.text
    assert "Картинки: 0/2" in page.text
    assert "Публикаций: 0" in page.text

    first_news = client.post(
        f"/drafts/{post_id}/generate-news",
        data={"csrf_token": token, "model": "gpt-image-1-mini"},
        follow_redirects=False,
    )
    assert first_news.status_code == 303
    second_news = client.post(
        f"/drafts/{post_id}/generate-news",
        data={"csrf_token": token, "model": "gpt-image-1-mini"},
        follow_redirects=False,
    )
    assert second_news.status_code == 400
    assert "лимит" in second_news.text.lower()

    for _ in range(2):
        image = client.post(
            f"/drafts/{post_id}/generate-image",
            data={"csrf_token": token, "model": "gpt-image-1-mini"},
            follow_redirects=False,
        )
        assert image.status_code == 303
        job_id = int(re.search(r"job=(\d+)", image.headers["location"]).group(1))
        db = SessionLocal()
        try:
            job = db.get(Job, job_id)
            job.status = "succeeded"
            db.commit()
        finally:
            db.close()

    third_image = client.post(
        f"/drafts/{post_id}/generate-image",
        data={"csrf_token": token, "model": "gpt-image-1-mini"},
        follow_redirects=False,
    )
    assert third_image.status_code == 400
    assert "лимит" in third_image.text.lower()

    page = client.get(f"/drafts/{post_id}")
    assert "Поиск: 1/1" in page.text
    assert "Картинки: 2/2" in page.text
    assert "Публикаций: 0" in page.text
