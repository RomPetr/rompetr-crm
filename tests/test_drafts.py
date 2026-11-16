from __future__ import annotations

import io
import re
from types import SimpleNamespace

from PIL import Image

from webapp.schemas.post_document import validate_platforms


def csrf(client) -> str:
    client.get("/login")
    return client.cookies.get("csrf_token")


def texts() -> dict[str, str]:
    link = "\n\nhttps://www.theblock.co/"
    return {
        "telegram": ("Т" * 850) + link,
        "vk": ("В" * 700) + " #криптовалюта #DeFi #DEX #onchain #мемкоины #аналитика" + link,
        "instagram": (" ".join(["слово"] * 120)) + " #crypto #defi #web3 #onchain #ai #dex" + link,
        "x": ("English text under two hundred eighty characters. " * 4) + link,
        "tiktok": (" ".join(["видео"] * 70)) + " #crypto #defi #onchain #web3" + link,
    }


def test_validator_limits():
    good = texts()
    assert validate_platforms(good) == []
    assert validate_platforms(good, "The Block") == []

    bad = dict(good)
    bad["x"] = "Кириллица в X"
    assert any("только английский" in item for item in validate_platforms(bad))

    no_vk_tags = dict(good)
    no_vk_tags["vk"] = "В" * 700
    assert not [item for item in validate_platforms(no_vk_tags) if item.startswith("vk")]

    bad = dict(good)
    bad["telegram"] = "коротко"
    assert any("telegram" in item for item in validate_platforms(bad))

    bad = dict(good)
    bad["vk"] = bad["vk"].replace("https://www.theblock.co/", "")
    assert any("ссылку на главную" in item for item in validate_platforms(bad, "The Block"))


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
        "image_enabled": "1",
        "enabled_telegram": "1",
        "enabled_vk": "1",
        "enabled_instagram": "1",
        "enabled_x": "1",
        "enabled_tiktok": "1",
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


def test_draft_flow_and_moderation(client, monkeypatch):
    monkeypatch.setattr(
        "webapp.services.vk.publish",
        lambda text: SimpleNamespace(
            ok=True, external_id="37", url="https://vk.com/wall-1_37", error=None, unknown=False
        ),
    )
    monkeypatch.setattr(
        "webapp.services.telegram.publish",
        lambda text, image_path: SimpleNamespace(
            ok=True, external_id="17", url="https://t.me/test/17", error=None, unknown=False
        ),
    )
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

    publish = client.post(f"/drafts/{post_id}/publish", data={"csrf_token": token}, follow_redirects=False)
    assert publish.status_code == 303
    page = client.get(f"/drafts/{post_id}")
    assert "Публикации" in page.text
    assert "manual_pending" in page.text


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

    download_match = re.search(r'href="(/drafts/\d+/assets/\d+/download)"', page.text)
    assert download_match, page.text
    download = client.get(download_match.group(1))
    assert download.status_code == 200
    disposition = download.headers["content-disposition"]
    assert "attachment" in disposition
    assert ".png" in disposition


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


def test_admin_sees_author_and_moderates_from_drafts(client):
    from webapp.db import SessionLocal
    from webapp.models.user import User
    from webapp.services.security import hash_password

    db = SessionLocal()
    try:
        if not db.query(User).filter(User.login == "chuttkii").first():
            db.add(
                User(
                    login="chuttkii",
                    email="chuttkii@example.com",
                    password_hash=hash_password("chuttkii-password-123"),
                    role="guest",
                    status="active",
                )
            )
            db.commit()
    finally:
        db.close()

    login(client, "chuttkii", "chuttkii-password-123")
    token = csrf(client)
    created = client.post(
        "/drafts/new", data={"csrf_token": token, "title": "второй"}, follow_redirects=False
    )
    post_id = int(created.headers["location"].rstrip("/").split("/")[-1])
    client.post(f"/drafts/{post_id}", data=form_payload(token, 1), follow_redirects=False)
    submitted = client.post(
        f"/drafts/{post_id}/submit", data={"csrf_token": token}, follow_redirects=False
    )
    assert submitted.status_code == 303

    login(client, "admin", "test-admin-password-12345")
    admin_token = csrf(client)
    listing = client.get("/drafts")
    assert listing.status_code == 200
    assert "chuttkii" in listing.text
    assert "Подтвердить" in listing.text

    approved = client.post(
        f"/admin/posts/{post_id}/approve", data={"csrf_token": admin_token}, follow_redirects=False
    )
    assert approved.status_code == 303

    page = client.get(f"/drafts/{post_id}")
    assert "Модерация:" in page.text
    assert "admin" in page.text


def test_job_wait_panel(client):
    from webapp.db import SessionLocal
    from webapp.models.system import Job

    login(client, "admin", "test-admin-password-12345")
    token = csrf(client)
    created = client.post(
        "/drafts/new", data={"csrf_token": token, "title": "Задача в работе"}, follow_redirects=False
    )
    post_id = int(created.headers["location"].rstrip("/").split("/")[-1])
    client.post(f"/drafts/{post_id}", data=form_payload(token, 1), follow_redirects=False)

    queued = client.post(
        f"/drafts/{post_id}/ai-check", data={"csrf_token": token}, follow_redirects=False
    )
    assert queued.status_code == 303
    page = client.get(queued.headers["location"])
    assert "Задача #" in page.text
    assert "в работе" in page.text
    assert 'id="job-timer"' in page.text
    assert "10–60 секунд" in page.text
    assert 'name="model"' in page.text
    assert "black-forest-labs/flux.2-pro" in page.text
    assert "gpt-image-1-mini" in page.text
    assert "Запустить" in page.text
    status_match = re.search(r'data-post-id="(\d+)" data-job-id="(\d+)"', page.text)
    assert status_match
    status = client.get(f"/drafts/{status_match.group(1)}/jobs/{status_match.group(2)}/status")
    assert status.status_code == 200
    assert status.json()["status"] in {"queued", "running"}

    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.post_id == post_id, Job.type == "ai_check").one()
        job.status = "succeeded"
        db.commit()
    finally:
        db.close()

    done = client.get(queued.headers["location"])
    assert "завершена" in done.text
    assert "AI-перевод и проверка выполнены" in done.text


def test_platform_toggles_exclude_disabled_fields(client):
    from webapp.db import SessionLocal
    from webapp.services import posts as posts_service

    login(client, "admin", "test-admin-password-12345")
    token = csrf(client)
    created = client.post(
        "/drafts/new", data={"csrf_token": token, "title": "Только Telegram и X"}, follow_redirects=False
    )
    post_id = int(created.headers["location"].rstrip("/").split("/")[-1])

    payload = form_payload(token, 1)
    for name in ("vk", "instagram", "tiktok"):
        payload.pop(f"enabled_{name}")
    client.post(f"/drafts/{post_id}", data=payload, follow_redirects=False)

    db = SessionLocal()
    try:
        from webapp.models.content import Post

        post = db.get(Post, post_id)
        enabled = posts_service.enabled_map(post)
        assert enabled["telegram"] and enabled["x"]
        assert not enabled["vk"] and not enabled["instagram"] and not enabled["tiktok"]
        assert posts_service.active_platforms(post).keys() == {"telegram", "x"}
        errors = posts_service.validate_post(post)
        assert errors == [], errors
    finally:
        db.close()

    page = client.get(f"/drafts/{post_id}")
    assert 'name="enabled_vk"' in page.text
    assert 'id="field_vk"' in page.text
    assert "disabled-field" in page.text
    assert "На проверку" not in page.text


def test_ai_change_badge(client):
    import uuid

    from webapp.db import SessionLocal
    from webapp.models.content import Post
    from webapp.models.system import Job

    login(client, "admin", "test-admin-password-12345")
    token = csrf(client)
    created = client.post(
        "/drafts/new", data={"csrf_token": token, "title": "С меткой правки"}, follow_redirects=False
    )
    post_id = int(created.headers["location"].rstrip("/").split("/")[-1])

    db = SessionLocal()
    try:
        post = db.get(Post, post_id)
        old_version = post.version
        post.version += 1
        db.add(
            Job(
                public_id=str(uuid.uuid4()),
                type="ai_check",
                status="succeeded",
                post_id=post.id,
                post_version=old_version,
                payload={"result": {"changes": {"telegram": "fixed"}}},
                idempotency_key=f"test-badge-{uuid.uuid4().hex}",
            )
        )
        db.commit()
    finally:
        db.close()

    page = client.get(f"/drafts/{post_id}")
    assert "Исправлено" in page.text
    assert "changed-field" in page.text


def test_compose_news_button_admin_only(client):
    login(client, "admin", "test-admin-password-12345")
    token = csrf(client)
    created = client.post(
        "/drafts/new", data={"csrf_token": token, "title": "Генерация"}, follow_redirects=False
    )
    post_id = int(created.headers["location"].rstrip("/").split("/")[-1])
    page = client.get(f"/drafts/{post_id}")
    assert "Сгенерировать новость" in page.text

    queued = client.post(
        f"/drafts/{post_id}/generate-news",
        data={"csrf_token": token, "model": "gpt-image-1-mini"},
        follow_redirects=False,
    )
    assert queued.status_code == 303
    assert "job=" in queued.headers["location"]

    login(client, "guest2", "guest2-password-123")
    guest_token = csrf(client)
    denied = client.post(
        f"/drafts/{post_id}/generate-news",
        data={"csrf_token": guest_token, "model": "gpt-image-1-mini"},
        follow_redirects=False,
    )
    assert denied.status_code in {403, 404}
