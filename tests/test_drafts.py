from __future__ import annotations

import io
import re

from PIL import Image

from webapp.schemas.post_document import validate_platforms


def csrf(client) -> str:
    client.get("/login")
    return client.cookies.get("csrf_token")


def texts() -> dict[str, str]:
    return {
        "telegram": "Т" * 850,
        "vk": ("В" * 700) + " #криптовалюта #DeFi #DEX #onchain #мемкоины #аналитика",
        "instagram": (" ".join(["слово"] * 120)) + " #crypto #defi #web3 #onchain #ai #dex",
        "x": "English text under two hundred eighty characters. " * 4,
        "tiktok": (" ".join(["видео"] * 70)) + " #crypto #defi #onchain #web3",
    }


def test_validator_limits():
    good = texts()
    assert validate_platforms(good) == []

    bad = dict(good)
    bad["x"] = "Кириллица в X"
    assert any("только английский" in item for item in validate_platforms(bad))

    bad = dict(good)
    bad["telegram"] = "коротко"
    assert any("telegram" in item for item in validate_platforms(bad))


def form_payload(token: str, version: int) -> dict:
    data = {
        "csrf_token": token,
        "version": str(version),
        "title": "Тестовый черновик",
        "source_title": "Test source title",
        "source_url": "https://www.theblock.co/news/test",
        "source_publisher": "The Block",
        "source_published_at": "2026-11-15",
        "image_prompt": "Cinematic 3D illustration of a glowing blockchain ledger, dark fintech aesthetic.",
    }
    data.update(texts())
    return data


def login(client, username: str, password: str) -> None:
    token = csrf(client)
    response = client.post(
        "/login",
        data={"csrf_token": token, "username": username, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text


def test_draft_flow_and_moderation(client):
    login(client, "admin", "test-admin-password-12345")
    token = csrf(client)

    created = client.post(
        "/drafts/new", data={"csrf_token": token, "title": "Тестовый черновик"}, follow_redirects=False
    )
    assert created.status_code == 303
    location = created.headers["location"]
    post_id = int(location.rstrip("/").split("/")[-1])

    saved = client.post(
        f"/drafts/{post_id}", data=form_payload(token, 1), follow_redirects=False
    )
    assert saved.status_code == 303

    checked = client.post(f"/drafts/{post_id}/check", data={"csrf_token": token}, follow_redirects=False)
    assert checked.status_code == 303

    submitted = client.post(f"/drafts/{post_id}/submit", data={"csrf_token": token}, follow_redirects=False)
    assert submitted.status_code == 303

    approved = client.post(
        f"/admin/posts/{post_id}/approve", data={"csrf_token": token}, follow_redirects=False
    )
    assert approved.status_code == 303

    publish = client.post(f"/drafts/{post_id}/publish", data={"csrf_token": token})
    assert publish.status_code == 501


def test_image_upload_and_private_media(client):
    login(client, "admin", "test-admin-password-12345")
    token = csrf(client)
    created = client.post(
        "/drafts/new", data={"csrf_token": token, "title": "Пост с картинкой"}, follow_redirects=False
    )
    post_id = int(created.headers["location"].rstrip("/").split("/")[-1])

    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), (30, 60, 200)).save(buffer, format="PNG")
    buffer.seek(0)

    uploaded = client.post(
        f"/drafts/{post_id}/assets",
        data={"csrf_token": token},
        files={"image": ("test.png", buffer.getvalue(), "image/png")},
        follow_redirects=False,
    )
    assert uploaded.status_code == 303

    page = client.get(f"/drafts/{post_id}")
    match = re.search(r'src="(/media/[^"]+)"', page.text)
    assert match, page.text
    media_url = match.group(1)

    media_response = client.get(media_url)
    assert media_response.status_code == 200
    assert media_response.headers["content-type"] == "image/png"


def test_guest_cannot_publish(client):
    from webapp.db import SessionLocal
    from webapp.models.user import User
    from webapp.services.security import hash_password

    db = SessionLocal()
    try:
        if not db.query(User).filter(User.login == "guest2").first():
            db.add(
                User(
                    login="guest2",
                    email="guest2@example.com",
                    password_hash=hash_password("guest2-password-123"),
                    role="guest",
                    status="active",
                )
            )
            db.commit()
    finally:
        db.close()

    login(client, "guest2", "guest2-password-123")
    token = csrf(client)
    created = client.post(
        "/drafts/new", data={"csrf_token": token, "title": "Гостевой черновик"}, follow_redirects=False
    )
    post_id = int(created.headers["location"].rstrip("/").split("/")[-1])
    publish = client.post(f"/drafts/{post_id}/publish", data={"csrf_token": token})
    assert publish.status_code == 403


def test_publisher_homepage_field(client):
    login(client, "admin", "test-admin-password-12345")
    token = csrf(client)
    created = client.post(
        "/drafts/new", data={"csrf_token": token, "title": "Проверка ссылки издания"}, follow_redirects=False
    )
    post_id = int(created.headers["location"].rstrip("/").split("/")[-1])
    page = client.get(f"/drafts/{post_id}")
    assert 'id="publisher-url"' in page.text
    assert 'id="publisher-link"' in page.text
    assert "/static/js/publisher.js" in page.text
    script = client.get("/static/js/publisher.js")
    assert script.status_code == 200
    assert "theblock.co" in script.text
