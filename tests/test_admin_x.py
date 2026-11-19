from __future__ import annotations

import io
import uuid
from pathlib import Path

from PIL import Image

from webapp.db import SessionLocal
from webapp.models.content import Post, Publication
from webapp.models.user import User
from webapp.services import media, posts


def make_x_post(db):
    admin = db.get(User, 0)
    post = posts.create_draft(db, admin, "X manual post")
    link = "\n\nhttps://www.theblock.co/"
    posts.apply_form(
        post,
        {
            "title": "X manual post",
            "source_title": "Source",
            "source_url": "https://www.theblock.co/news/test",
            "source_publisher": "The Block",
            "source_published_at": "2026-11-16",
            "image_prompt": "Cinematic 3D illustration of a glowing ledger, dark fintech aesthetic.",
            "image_enabled": "1",
            "enabled_x": "1",
            "x": "English tweet text " * 5 + link,
        },
        1,
    )
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(buffer, format="PNG")
    media.save_bytes(db, post, buffer.getvalue(), 0)
    posts.approve(db, post, admin)
    publication = Publication(
        post_id=post.id,
        platform="x",
        status="manual_pending",
        idempotency_key=f"test-x-{uuid.uuid4().hex}",
        external_url="https://x.com/intent/post?text=test",
    )
    db.add(publication)
    db.commit()
    return post, publication


def csrf(client) -> str:
    client.get("/login")
    return client.cookies.get("csrf_token")


def test_x_manual_actions(client, monkeypatch):
    db = SessionLocal()
    try:
        post, publication = make_x_post(db)
        post_id, publication_id = post.id, publication.id
    finally:
        db.close()

    token = csrf(client)
    login = client.post(
        "/login",
        data={"csrf_token": token, "username": "admin", "password": "test-admin-password-12345"},
        follow_redirects=False,
    )
    assert login.status_code == 303

    page = client.get("/admin/publications")
    assert "Открыть X с картинкой" in page.text
    assert "Скачать картинку" in page.text

    image = client.get(f"/admin/publications/{publication_id}/image")
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"

    calls = []

    def fake_popen(args, **kwargs):
        calls.append(args)

        class Dummy:
            pass

        return Dummy()

    real_exists = Path.exists

    def fake_exists(self):
        return True if self.name == "x_compose.cjs" else real_exists(self)

    monkeypatch.setattr(Path, "exists", fake_exists)
    monkeypatch.setattr("webapp.routers.admin.shutil.which", lambda _: "/usr/bin/node")
    monkeypatch.setattr("webapp.routers.admin.subprocess.Popen", fake_popen)
    opened = client.post(
        f"/admin/publications/{publication_id}/x-compose",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert opened.status_code == 303
    assert "x=opened" in opened.headers["location"]
    assert calls and "x_compose.cjs" in calls[0][1]

    db = SessionLocal()
    try:
        post = db.get(Post, post_id)
        assert post is not None
    finally:
        db.close()
