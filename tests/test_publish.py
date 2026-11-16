from __future__ import annotations

from types import SimpleNamespace

from webapp.db import SessionLocal
from webapp.models.content import Post, Publication
from webapp.models.user import User
from webapp.services import posts, publish


def texts() -> dict[str, str]:
    return {
        "telegram": "Т" * 850,
        "vk": ("В" * 700) + " #криптовалюта #DeFi #DEX #onchain #мемкоины #аналитика",
        "instagram": ("слово " * 120) + "#crypto #defi #web3 #onchain #ai #dex",
        "x": "English text under two hundred eighty characters. " * 4,
        "tiktok": ("видео " * 70) + "#crypto #defi #onchain #web3",
    }


def make_approved_post(db, title: str) -> Post:
    admin = db.get(User, 0)
    post = posts.create_draft(db, admin, title)
    payload = {
        "title": title,
        "source_title": "Test source",
        "source_url": "https://www.theblock.co/news/test",
        "source_publisher": "The Block",
        "source_published_at": "2026-11-15",
        "image_prompt": "Cinematic 3D illustration of a glowing blockchain ledger, dark fintech aesthetic.",
        **texts(),
    }
    posts.apply_form(post, payload, 1)
    errors = posts.submit_for_review(db, post)
    assert errors == []
    posts.approve(db, post, admin)
    db.commit()
    return post


def test_publish_is_idempotent(monkeypatch):
    calls = {"vk": 0, "telegram": 0}

    def fake_vk(text):
        calls["vk"] += 1
        return SimpleNamespace(
            ok=True,
            external_id="37",
            url="https://vk.com/wall-243080370_37",
            error=None,
            unknown=False,
        )

    def fake_tg(text, image_path):
        calls["telegram"] += 1
        return SimpleNamespace(ok=True, external_id="17", url="https://t.me/defidexmind/17", error=None, unknown=False)

    monkeypatch.setattr("webapp.services.vk.publish", fake_vk)
    monkeypatch.setattr("webapp.services.telegram.publish", fake_tg)

    db = SessionLocal()
    try:
        post = make_approved_post(db, "Idempotent post")
        admin = db.get(User, 0)
        first = publish.publish_post(db, post, admin)
        db.commit()
        second = publish.publish_post(db, post, admin)
        db.commit()

        assert calls == {"vk": 1, "telegram": 1}
        assert post.status == "published"
        assert [item.status for item in first].count("published") == 2
        assert [item.status for item in second].count("published") == 2

        pubs = db.query(Publication).filter(Publication.post_id == post.id).all()
        assert len(pubs) == 3
        x_pub = next(item for item in pubs if item.platform == "x")
        assert x_pub.status == "manual_pending"
        assert x_pub.external_url and x_pub.external_url.startswith("https://x.com/intent/post?text=")
    finally:
        db.close()


def test_unknown_is_not_retried(monkeypatch):
    calls = {"telegram": 0}

    def fake_vk(text):
        return SimpleNamespace(ok=True, external_id="1", url="https://vk.com/wall-1_1", error=None, unknown=False)

    def fake_tg(text, image_path):
        calls["telegram"] += 1
        return SimpleNamespace(
            ok=False, external_id=None, url=None, error="timeout", unknown=True
        )

    monkeypatch.setattr("webapp.services.vk.publish", fake_vk)
    monkeypatch.setattr("webapp.services.telegram.publish", fake_tg)

    db = SessionLocal()
    try:
        post = make_approved_post(db, "Unknown post")
        admin = db.get(User, 0)
        publish.publish_post(db, post, admin)
        db.commit()
        publish.publish_post(db, post, admin)
        db.commit()

        assert calls["telegram"] == 1
        telegram_pub = (
            db.query(Publication)
            .filter(Publication.post_id == post.id, Publication.platform == "telegram")
            .one()
        )
        assert telegram_pub.status == "unknown"
    finally:
        db.close()
