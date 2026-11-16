from __future__ import annotations

import json
import logging
import re
import signal
import sys
import threading
from datetime import date, datetime, timezone
from datetime import time as dt_time
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.orm import Session

from webapp.config import ROOT, get_settings
from webapp.db import SessionLocal
from webapp.logging import configure_logging
from webapp.models.content import Post
from webapp.models.system import Job
from webapp.schemas.post_document import PostDocumentPartial
from webapp.services import claude_runner, images, jobs
from webapp.services import posts as posts_service

log = logging.getLogger(__name__)
PLATFORMS = ("telegram", "instagram", "x", "tiktok", "vk")


def document_for(post: Post) -> dict:
    enabled = posts_service.enabled_map(post)
    return {
        "schema_version": "crypto-ai-social-content/v1",
        "source": {
            "title": post.source_title,
            "url": post.source_url,
            "published_at": post.source_published_at.date().isoformat()
            if post.source_published_at
            else None,
            "publisher": post.source_publisher,
        },
        "image_prompt": post.image_prompt if post.image_enabled else "",
        "platforms": {
            name: {"content": (post.platforms or {}).get(name, "")}
            for name in PLATFORMS
            if enabled.get(name)
        },
    }


def _check_prompt(path: Path) -> str:
    return (
        "Ты переводчик и редактор Content Plant. В файле "
        f"{path} есть только включённые пользователем площадки. "
        "Переведи тексты telegram, vk, instagram и tiktok на русский язык, "
        "сохранив смысл, факты и цифры. Если текст уже на русском — отредактируй "
        "орфографию, грамматику, пунктуацию и кальку. Поле x не переводи: "
        "оно должно остаться на английском, но проверь его английский и длину. "
        "Не добавляй новых фактов. В каждой площадке последняя строка — ссылка "
        "на главную страницу издания из source.publisher. Не меняй source. "
        "Правь JSON только через Edit/Write. В ответе верни короткий вердикт "
        "PASS или NEEDS_FIX и список переводов/правок."
    )


def _apply_document(post: Post, document: PostDocumentPartial) -> None:
    post.source_title = document.source.title
    post.source_url = str(document.source.url)
    post.source_publisher = document.source.publisher
    published = document.source.published_at
    post.source_published_at = (
        datetime.combine(published, dt_time.min, tzinfo=timezone.utc)
        if isinstance(published, date)
        else post.source_published_at
    )
    if post.image_enabled and document.image_prompt:
        post.image_prompt = document.image_prompt
    platforms = dict(post.platforms or {})
    for name in PLATFORMS:
        item = getattr(document.platforms, name, None)
        if item is not None:
            platforms[name] = item.content
    post.platforms = platforms
    post.version += 1


def run_ai_check(db: Session, job: Job) -> dict:
    post = db.get(Post, job.post_id) if job.post_id else None
    if post is None:
        raise RuntimeError("Пост не найден")
    folder = ROOT / "var" / "jobs" / job.public_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "post.json"
    path.write_text(json.dumps(document_for(post), ensure_ascii=False, indent=2), encoding="utf-8")
    enabled = posts_service.enabled_map(post)
    before = {
        name: (post.platforms or {}).get(name, "")
        for name in PLATFORMS
        if enabled.get(name)
    }
    before_image = post.image_prompt if post.image_enabled else ""

    result = claude_runner.run(_check_prompt(path), job.public_id)
    if result.timed_out:
        raise RuntimeError(f"Claude Code не уложился в таймаут. Лог: {result.log_path}")
    if result.exit_code != 0:
        detail = (result.stderr or "").strip()
        if not detail:
            detail = str((result.parsed or {}).get("result") or "").strip()
        if not detail:
            detail = (result.stdout or "")[-500:]
        raise RuntimeError(f"Claude Code exit {result.exit_code}: {detail}. Лог: {result.log_path}")

    try:
        document = PostDocumentPartial.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (ValidationError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Checker вернул невалидный JSON: {exc}") from exc

    changes: dict[str, str] = {}
    for name, old_text in before.items():
        item = getattr(document.platforms, name, None)
        if item is None or item.content == old_text:
            continue
        had_cyrillic = bool(re.search(r"[А-Яа-яЁё]", old_text))
        has_cyrillic = bool(re.search(r"[А-Яа-яЁё]", item.content))
        changes[name] = "translated" if not had_cyrillic and has_cyrillic else "fixed"
    if post.image_enabled and document.image_prompt and document.image_prompt != before_image:
        changes["image_prompt"] = "fixed"

    _apply_document(post, document)
    return {
        "verdict": (result.parsed or {}).get("result", "unknown")[:1000],
        "changes": changes,
        "log": result.log_path,
    }


def run_generate_image(db: Session, job: Job) -> dict:
    post = db.get(Post, job.post_id) if job.post_id else None
    if post is None:
        raise RuntimeError("Пост не найден")
    asset = images.generate(db, post, job.created_by, (job.payload or {}).get("model"))
    return {"asset_id": asset.id, "storage_key": asset.storage_key, "bytes": asset.bytes}


def process(db: Session, job: Job) -> None:
    try:
        if job.type == "ai_check":
            result = run_ai_check(db, job)
        elif job.type == "generate_image":
            result = run_generate_image(db, job)
        else:
            raise RuntimeError(f"Неизвестный тип задачи: {job.type}")
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        job = db.get(Job, job.id)
        if job is not None:
            jobs.fail(db, job, str(exc), retry=True)
            db.commit()
        log.exception("job %s failed", job.id if job else "?")
        return
    jobs.succeed(db, job, result=result)
    db.commit()


def run_once(worker_id: str) -> bool:
    db = SessionLocal()
    try:
        jobs.requeue_stale(db)
        job = jobs.claim_next(db, worker_id)
        if job is None:
            db.commit()
            return False
        process(db, job)
        return True
    finally:
        db.close()


def loop(stop: threading.Event, worker_id: str) -> None:
    settings = get_settings()
    log.info("worker %s started", worker_id)
    while not stop.is_set():
        try:
            did_work = run_once(worker_id)
        except Exception:  # noqa: BLE001
            log.exception("worker iteration failed")
            did_work = False
        if not did_work:
            stop.wait(settings.worker_poll_sec)
    log.info("worker stopped")


def main() -> int:
    import argparse

    settings = get_settings()
    configure_logging()
    parser = argparse.ArgumentParser(prog="webapp.worker")
    parser.add_argument("--once", action="store_true", help="обработать одну задачу и выйти")
    args = parser.parse_args()
    if args.once:
        processed = run_once(settings.worker_id)
        print("job processed" if processed else "queue is empty")
        return 0

    stop = threading.Event()

    def handler(signum, frame):  # type: ignore[no-untyped-def]
        stop.set()

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)
    loop(stop, settings.worker_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
