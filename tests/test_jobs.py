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


def compose_data(url: str, title: str = "Generated news title") -> dict:
    return {
        "schema_version": "crypto-ai-social-content/v1",
        "source": {
            "title": title,
            "url": url,
            "published_at": "2026-11-16",
            "publisher": "The Block",
        },
        "image_prompt": "Cinematic 3D illustration of a generated news scene, dark fintech aesthetic.",
        "platforms": {name: {"content": text} for name, text in texts().items()},
    }


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
        data["platforms"]["telegram"]["content"] = (
            "Исправленный текст. " + ("Т" * 830) + "\n\nhttps://www.theblock.co/"
        )
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


def test_ai_check_rejects_oversized_telegram(monkeypatch):
    def fake_run(prompt, job_id, timeout_sec=None):
        path = ROOT / "var" / "jobs" / job_id / "post.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["platforms"]["telegram"]["content"] = (
            ("Т" * 1040) + "\n\nhttps://www.theblock.co/"
        )
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
        post = make_draft(db, "AI check oversized")
        old_telegram = post.platforms["telegram"]
        old_version = post.version
        job = jobs.enqueue(db, "ai_check", post, created_by=0)
        job.max_attempts = 1
        job.attempts = 1
        db.commit()
        process(db, job)
        db.refresh(job)
        db.refresh(post)
        assert job.status == "failed"
        assert "вне лимитов" in (job.error or "")
        assert post.platforms["telegram"] == old_telegram
        assert post.version == old_version
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
    prompts = []

    def fake_run(prompt, job_id, timeout_sec=None, allowed_tools=None, **kwargs):
        assert kwargs["max_budget_usd"] >= 6
        prompts.append(prompt)
        path = ROOT / "var" / "jobs" / job_id / "post.json"
        data = compose_data("https://www.theblock.co/news/generated")
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
        used = make_draft(db, "Used source")
        used.source_title = "Used before"
        used.source_url = "https://www.theblock.co/news/used-before"
        db.commit()
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
        assert "https://www.theblock.co/news/used-before" in prompts[0]
        assert "повторять нельзя" in prompts[0]
    finally:
        db.close()


def test_compose_news_repairs_text_over_limit(monkeypatch):
    prompts = []
    fix_tools = []
    paths = {}

    def fake_run(prompt, job_id, timeout_sec=None, allowed_tools=None, **kwargs):
        prompts.append(prompt)
        if job_id.endswith("-fix"):
            fix_tools.append(allowed_tools)
            path = paths["post"]
            data = json.loads(path.read_text(encoding="utf-8"))
            data["platforms"]["telegram"]["content"] = (
                ("Т" * 830) + "\n\nhttps://www.theblock.co/"
            )
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        else:
            path = ROOT / "var" / "jobs" / job_id / "post.json"
            paths["post"] = path
            data = compose_data("https://www.theblock.co/news/repair-length")
            data["platforms"]["telegram"]["content"] = (
                ("Т" * 1180) + "\n\nhttps://www.theblock.co/"
            )
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return SimpleNamespace(
            exit_code=0, stdout="", stderr="", parsed={"result": "PASS"}, timed_out=False, log_path=None
        )

    monkeypatch.setattr("webapp.worker.claude_runner.run", fake_run)
    monkeypatch.setattr(
        "webapp.services.images.generate",
        lambda db, post, user_id, model=None: SimpleNamespace(id=57, storage_key="posts/x/57.png", bytes=10),
    )

    db = SessionLocal()
    try:
        post = make_draft(db, "Compose over limit")
        job = jobs.enqueue(db, "compose_news", post, created_by=0)
        db.commit()
        process(db, job)
        db.refresh(job)
        db.refresh(post)
        assert job.status == "succeeded", job.error
        assert len(prompts) == 2
        assert "нужно 800–1024" in prompts[1]
        assert fix_tools == [("Read", "Edit", "Write")]
        assert 800 <= len(post.platforms["telegram"]) <= 1024
        assert post.source_url == "https://www.theblock.co/news/repair-length"
    finally:
        db.close()


def test_compose_news_rejects_when_repair_still_over_limit(monkeypatch):
    paths = {}

    def fake_run(prompt, job_id, timeout_sec=None, allowed_tools=None, **kwargs):
        if not job_id.endswith("-fix"):
            path = ROOT / "var" / "jobs" / job_id / "post.json"
            paths["post"] = path
            data = compose_data("https://www.theblock.co/news/repair-failed")
            data["platforms"]["telegram"]["content"] = (
                ("Т" * 1180) + "\n\nhttps://www.theblock.co/"
            )
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return SimpleNamespace(
            exit_code=0, stdout="", stderr="", parsed={"result": "PASS"}, timed_out=False, log_path=None
        )

    monkeypatch.setattr("webapp.worker.claude_runner.run", fake_run)

    db = SessionLocal()
    try:
        post = make_draft(db, "Compose repair failed")
        job = jobs.enqueue(db, "compose_news", post, created_by=0)
        job.attempts = 1
        db.commit()
        process(db, job)
        db.refresh(job)
        db.refresh(post)
        assert job.status == "failed"
        assert "Новость не прошла проверку" in (job.error or "")
        assert "нужно 800–1024" in (job.error or "")
        assert post.source_url == "https://www.theblock.co/news/test"
    finally:
        db.close()


def test_compose_news_rejects_duplicate_source(monkeypatch):
    def fake_run(prompt, job_id, timeout_sec=None, allowed_tools=None, **kwargs):
        path = ROOT / "var" / "jobs" / job_id / "post.json"
        data = compose_data("https://www.theblock.co/news/duplicate-source/")
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return SimpleNamespace(
            exit_code=0, stdout="", stderr="", parsed={"result": "PASS"}, timed_out=False, log_path=None
        )

    monkeypatch.setattr("webapp.worker.claude_runner.run", fake_run)

    db = SessionLocal()
    try:
        existing = make_draft(db, "Existing duplicate")
        existing.source_title = "Duplicate source"
        existing.source_url = "https://www.theblock.co/news/duplicate-source"
        target = make_draft(db, "Duplicate target")
        target.source_title = ""
        target.source_url = ""
        db.commit()
        job = jobs.enqueue(db, "compose_news", target, created_by=0)
        job.attempts = 1
        db.commit()
        process(db, job)
        db.refresh(job)
        db.refresh(target)
        assert job.status == "failed"
        assert "уже использована" in (job.error or "")
        assert f"#{existing.id}" in (job.error or "")
        assert target.source_url == ""
    finally:
        db.close()


def test_compose_news_skips_disabled_platforms(monkeypatch):
    """Выключенные площадки не готовятся и не перезаписываются compose-задачей."""
    prompts = []

    def fake_run(prompt, job_id, timeout_sec=None, allowed_tools=None, **kwargs):
        prompts.append(prompt)
        path = ROOT / "var" / "jobs" / job_id / "post.json"
        data = compose_data("https://www.theblock.co/news/generated-disabled")
        data["platforms"]["instagram"] = {"content": "Модель проигнорировала инструкцию"}
        data["platforms"]["tiktok"] = {"content": "Модель проигнорировала инструкцию"}
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return SimpleNamespace(
            exit_code=0, stdout="", stderr="", parsed={"result": "PASS"},
            timed_out=False, log_path=None,
        )

    monkeypatch.setattr("webapp.worker.claude_runner.run", fake_run)
    monkeypatch.setattr(
        "webapp.services.images.generate",
        lambda db, post, user_id, model=None: SimpleNamespace(
            id=56, storage_key="posts/x/56.png", bytes=10
        ),
    )

    db = SessionLocal()
    try:
        post = make_draft(db, "Compose with disabled platforms")
        post.platforms_enabled = {
            "telegram": True, "vk": True, "instagram": False, "x": True, "tiktok": False,
        }
        post.platforms = {**post.platforms, "instagram": "старый текст", "tiktok": "старый текст"}
        db.commit()
        job = jobs.enqueue(db, "compose_news", post, created_by=0)
        db.commit()
        process(db, job)
        db.refresh(job)
        db.refresh(post)
        assert job.status == "succeeded", job.error
        prompt = prompts[0]
        assert "Выключенные площадки (instagram, tiktok)" in prompt
        assert "Instagram 100–200 слов" not in prompt
        assert "TikTok 50–120 слов" not in prompt
        assert "Telegram 800–1024" in prompt
        assert post.platforms_enabled["instagram"] is False
        assert post.platforms_enabled["tiktok"] is False
        assert post.platforms["instagram"] == "старый текст"
        assert post.platforms["tiktok"] == "старый текст"
        assert post.platforms["telegram"].startswith("Т")
    finally:
        db.close()
