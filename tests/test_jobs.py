from __future__ import annotations

import json
from types import SimpleNamespace

from webapp.config import ROOT
from webapp.db import SessionLocal
from webapp.models.user import User
from webapp.services import jobs, posts
from webapp.worker import process


def texts() -> dict[str, str]:
    link = "\n\nhttps://www.theblock.co/"
    return {
        "telegram": ("Т" * 850) + link,
        "vk": ("В" * 700) + " #криптовалюта #DeFi #DEX #onchain #мемкоины #аналитика" + link,
        "instagram": ("слово " * 120) + "#crypto #defi #web3 #onchain #ai #dex" + link,
        "x": ("English text under two hundred eighty characters. " * 4) + link,
        "tiktok": ("видео " * 70) + "#crypto #defi #onchain #web3" + link,
    }


def make_draft(db, title: str):
    from webapp.models.system import Job

    db.query(Job).filter(Job.status.in_(["queued", "running"])).delete()
    db.commit()
    admin = db.get(User, 0)
    post = posts.create_draft(db, admin, title)
    posts.apply_form(
        post,
        {
            "title": title,
            "source_title": "Test source",
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
            **texts(),
        },
        1,
    )
    db.commit()
    return post


def test_enqueue_is_idempotent_and_claims():
    db = SessionLocal()
    try:
        post = make_draft(db, "Job idempotency")
        first = jobs.enqueue(db, "generate_image", post, created_by=0)
        second = jobs.enqueue(db, "generate_image", post, created_by=0)
        db.commit()
        assert first.id == second.id

        claimed = jobs.claim_next(db, "test-worker")
        assert claimed is not None
        assert claimed.id == first.id
        assert claimed.status == "running"
        jobs.succeed(db, claimed, result={"ok": True})
        db.commit()
        assert claimed.status == "succeeded"
    finally:
        db.close()


def test_generate_image_job(monkeypatch):
    seen = {}

    def fake_generate(db, post, user_id, model=None):
        seen["model"] = model
        return SimpleNamespace(id=99, storage_key="posts/x/y.png", bytes=1234)

    monkeypatch.setattr("webapp.services.images.generate", fake_generate)

    db = SessionLocal()
    try:
        post = make_draft(db, "Image job")
        job = jobs.enqueue(
            db, "generate_image", post, created_by=0, payload={"model": "gpt-image-1-mini"}
        )
        db.commit()
        process(db, job)
        db.refresh(job)
        assert job.status == "succeeded"
        assert job.payload["result"]["asset_id"] == 99
        assert seen["model"] == "gpt-image-1-mini"
    finally:
        db.close()


def test_ai_check_job_updates_post(monkeypatch):
    def fake_run(prompt, job_id, timeout_sec=None):
        path = ROOT / "var" / "jobs" / job_id / "post.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["platforms"]["telegram"]["content"] = "Исправленный текст.\n\nhttps://www.theblock.co/"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return SimpleNamespace(
            exit_code=0,
            stdout="",
            stderr="",
            parsed={"result": "PASS"},
            timed_out=False,
            log_path=None,
        )

    monkeypatch.setattr("webapp.worker.claude_runner.run", fake_run)

    db = SessionLocal()
    try:
        post = make_draft(db, "AI check job")
        old_version = post.version
        job = jobs.enqueue(db, "ai_check", post, created_by=0)
        db.commit()
        process(db, job)
        db.refresh(job)
        db.refresh(post)
        assert job.status == "succeeded"
        assert post.platforms["telegram"].startswith("Исправленный текст.")
        assert post.version == old_version + 1
        assert job.payload["result"]["changes"]["telegram"] == "fixed"
    finally:
        db.close()


def test_regenerate_after_success_creates_new_job(monkeypatch):
    monkeypatch.setattr(
        "webapp.services.images.generate",
        lambda db, post, user_id, model=None: SimpleNamespace(id=1, storage_key="posts/a/b.png", bytes=1),
    )
    db = SessionLocal()
    try:
        post = make_draft(db, "Regenerate image")
        first = jobs.enqueue(db, "generate_image", post, created_by=0)
        db.commit()
        claimed = jobs.claim_next(db, "w")
        jobs.succeed(db, claimed, result={"asset_id": 1})
        db.commit()

        second = jobs.enqueue(db, "generate_image", post, created_by=0)
        db.commit()
        assert second.id != first.id
        assert second.status == "queued"
    finally:
        db.close()


def test_failed_ai_check_requeues_same_job():
    db = SessionLocal()
    try:
        post = make_draft(db, "Retry AI check")
        job = jobs.enqueue(db, "ai_check", post, created_by=0)
        db.commit()
        claimed = jobs.claim_next(db, "w")
        claimed.attempts = claimed.max_attempts
        jobs.fail(db, claimed, "boom", retry=False)
        db.commit()
        assert claimed.status == "failed"

        again = jobs.enqueue(db, "ai_check", post, created_by=0)
        db.commit()
        assert again.id == job.id
        assert again.status == "queued"
        assert again.attempts == 0
    finally:
        db.close()


def test_document_for_contains_only_enabled_platforms():
    from webapp.worker import document_for

    db = SessionLocal()
    try:
        post = make_draft(db, "Partial document")
        post.platforms_enabled = {
            "telegram": True,
            "vk": False,
            "instagram": False,
            "x": True,
            "tiktok": False,
        }
        post.image_enabled = False
        db.commit()
        document = document_for(post)
        assert set(document["platforms"]) == {"telegram", "x"}
        assert document["image_prompt"] == ""
    finally:
        db.close()


def test_compose_news_job(monkeypatch):
    import json

    from webapp.config import ROOT

    def fake_run(prompt, job_id, timeout_sec=None, allowed_tools=None, **kwargs):
        assert kwargs["max_budget_usd"] >= 6
        path = ROOT / "var" / "jobs" / job_id / "post.json"
        data = {
            "schema_version": "crypto-ai-social-content/v1",
            "source": {
                "title": "Generated news title",
                "url": "https://www.theblock.co/news/generated",
                "published_at": "2026-11-16",
                "publisher": "The Block",
            },
            "image_prompt": "Cinematic 3D illustration of a generated news scene, dark fintech aesthetic.",
            "platforms": {name: {"content": text} for name, text in texts().items()},
        }
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return SimpleNamespace(
            exit_code=0, stdout="", stderr="", parsed={"result": "PASS"}, timed_out=False, log_path=None
        )

    monkeypatch.setattr("webapp.worker.claude_runner.run", fake_run)
    monkeypatch.setattr(
        "webapp.services.images.generate",
        lambda db, post, user_id, model=None: SimpleNamespace(id=55, storage_key="posts/x/55.png", bytes=10),
    )

    db = SessionLocal()
    try:
        post = make_draft(db, "Compose target")
        job = jobs.enqueue(
            db, "compose_news", post, created_by=0, payload={"model": "gpt-image-1-mini"}
        )
        assert job.max_attempts == 1
        db.commit()
        process(db, job)
        db.refresh(job)
        db.refresh(post)
        assert job.status == "succeeded", job.error
        assert post.source_publisher == "The Block"
        assert post.source_title == "Generated news title"
        assert post.platforms["telegram"].startswith("Т")
        assert job.payload["result"]["asset_id"] == 55
    finally:
        db.close()
