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
from urllib.parse import urlsplit, urlunsplit

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from webapp.config import ROOT, get_settings
from webapp.db import SessionLocal
from webapp.logging import configure_logging
from webapp.models.content import Post
from webapp.models.system import Job
from webapp.schemas.post_document import PostDocument, PostDocumentPartial, validate_document
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
        "После перевода обязательно пересчитай длину каждой включённой площадки "
        "вместе со ссылкой: Telegram 800–1024 символа, VK 700–1500, X до 280 "
        "(только английский), Instagram 100–200 слов и 5–10 хэштегов, "
        "TikTok 50–120 слов и 3–5 хэштегов. Перевод часто удлиняет текст: если "
        "Telegram стал длиннее 1024 символов, сокращай формулировки, сохраняя "
        "факты и цифры, пока не войдёшь в лимит. Не сдавай файл с превышением. "
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
        detail = str((result.parsed or {}).get("result") or "").strip()
        if not detail:
            detail = (result.stderr or "").strip()
        if not detail:
            detail = (result.stdout or "")[-500:]
        raise RuntimeError(f"Claude Code exit {result.exit_code}: {detail}. Лог: {result.log_path}")

    try:
        document = PostDocumentPartial.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (ValidationError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Checker вернул невалидный JSON: {exc}") from exc

    source = {
        "title": document.source.title,
        "url": str(document.source.url),
        "published_at": document.source.published_at,
        "publisher": document.source.publisher,
    }
    platforms = {
        name: item.content
        for name in PLATFORMS
        if (item := getattr(document.platforms, name, None)) is not None
    }
    errors = validate_document(
        source,
        document.image_prompt,
        platforms,
        check_prompt=post.image_enabled,
    )
    if errors:
        raise RuntimeError("Checker вернул текст вне лимитов: " + "; ".join(errors[:8]))

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


USED_SOURCE_LIMIT = 40


def _canonical_source_url(url: str) -> str:
    """Ссылка без различий в регистре хоста, якоре и хвостовом слеше."""
    value = url.strip()
    try:
        parts = urlsplit(value)
    except ValueError:
        return value.lower()
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), parts.query, "")
    )


def _used_sources(db: Session, limit: int = USED_SOURCE_LIMIT) -> list[tuple[str, str]]:
    """Последние использованные новости, чтобы модель не выбрала их повторно."""
    rows = db.execute(
        select(Post.source_title, Post.source_url)
        .where(Post.source_url.is_not(None), Post.source_url != "")
        .order_by(Post.updated_at.desc())
        .limit(limit)
    ).all()
    return [(title or url, url) for title, url in rows]


def _duplicate_source_post(db: Session, url: str) -> int | None:
    target = _canonical_source_url(url)
    rows = db.execute(
        select(Post.id, Post.source_url).where(
            Post.source_url.is_not(None), Post.source_url != ""
        )
    ).all()
    for post_id, existing in rows:
        if _canonical_source_url(existing) == target:
            return int(post_id)
    return None


PLATFORM_RULES = {
    "telegram": "Telegram 800–1024 символа включая ссылку, без хэштегов.",
    "vk": "VK 700–1500 символов включая ссылку; хэштеги не обязательны.",
    "instagram": "Instagram 100–200 слов включая ссылку, 5–10 хэштегов.",
    "tiktok": "TikTok 50–120 слов включая ссылку, 3–5 хэштегов.",
    "x": (
        "X до 280 символов включая ссылку; хэштегов 0, максимум 1 только для "
        "события. Общие #crypto/#DeFi/#DEX не добавляй; для конкретной монеты "
        "используй cashtag $BTC/$XRP, не #BTC."
    ),
}


def _compose_prompt(
    path: Path, used_sources: list[tuple[str, str]], enabled: tuple[str, ...]
) -> str:
    used_block = ""
    if used_sources:
        items = "\n".join(f"- {title} — {url}" for title, url in used_sources)
        used_block = f"""
Уже использованные новости (повторять нельзя, даже если они ещё есть в лентах):
{items}
"""
    disabled = [name for name in PLATFORMS if name not in enabled]
    example = ", ".join(
        f'"{name}": {{"content": {json.dumps("…" if name in enabled else "", ensure_ascii=False)}}}'
        for name in PLATFORMS
    )
    if enabled:
        scope_line = f"Включённые площадки, для которых пиши текст: {', '.join(enabled)}."
        if disabled:
            scope_line += (
                f" Выключенные площадки ({', '.join(disabled)}) не готовь: у них "
                'content — пустая строка "".'
            )
    else:
        scope_line = (
            'Включённых площадок нет: во всех пяти ключах content — пустая '
            'строка "", тексты не пиши.'
        )

    rules = []
    ru = [name for name in ("telegram", "vk", "instagram", "tiktok") if name in enabled]
    if ru:
        rules.append(f"- русский для {', '.join(ru)}.")
    if "x" in enabled:
        rules.append("- x только английский.")
    if enabled:
        rules.append(
            "- Последняя строка каждой включённой площадки — ссылка на главную "
            "источника: The Block https://www.theblock.co/, The Defiant "
            "https://thedefiant.io/, Blockworks https://blockworks.co/, CoinDesk "
            "https://www.coindesk.com/, Decrypt https://decrypt.co/."
        )
    for name in PLATFORMS:
        if name in enabled:
            rules.append(f"- {PLATFORM_RULES[name]}")
    rules_block = "\n".join(rules)

    return f"""Ты Content Plant для сообщества «Разум DEX». Найди одну свежую новость за сегодня или вчера и запиши её в JSON {path}.

Источники (используй WebFetch):
- The Block: https://www.theblock.co/rss.xml
- The Defiant: https://thedefiant.io/api/feed
- Blockworks: https://blockworks.co/feed
- CoinDesk: https://www.coindesk.com/arc/outboundfeeds/rss/
- Decrypt: https://decrypt.co/feed
{used_block}
Приоритет: DEX/AMM/DeFi, AI-агенты, торговые боты, кошельки и безопасность, on-chain-аналитика, регулирование. Не бери чистые движения цены. Открой статью через WebFetch и проверь факты. Если подходящая по приоритету новость уже есть в списке использованных, пропусти её и возьми следующую свежую новость из любого источника.

Запиши JSON строго по схеме:
schema_version "crypto-ai-social-content/v1";
source: title, url полной статьи, published_at YYYY-MM-DD, publisher одно из The Block, The Defiant, Blockworks, CoinDesk, Decrypt;
image_prompt: английский, 2-4 предложения, без текста/логотипов/людей;
platforms: объект со всеми пятью ключами telegram, instagram, x, tiktok, vk; значение каждой площадки — объект {{"content": "текст"}}. {scope_line} Например:
"platforms": {{{example}}}.

Правила текстов:
{rules_block}
- Факты, цифры и даты — только из источника. Без обещаний доходности и секретов.
Правь файл через Write. Не запускай субагентов и Bash: длины текстов считай сам.
Запиши готовый JSON один раз и заверши работу. В ответе верни короткий PASS и заголовок новости."""


def run_compose_news(db: Session, job: Job) -> dict:
    settings = get_settings()
    post = db.get(Post, job.post_id) if job.post_id else None
    if post is None:
        raise RuntimeError("Пост не найден")
    folder = ROOT / "var" / "jobs" / job.public_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "post.json"
    enabled = posts_service.enabled_map(post)

    result = claude_runner.run(
        _compose_prompt(
            path,
            _used_sources(db),
            tuple(name for name in PLATFORMS if enabled[name]),
        ),
        job.public_id,
        timeout_sec=1200,
        allowed_tools=("Read", "Write", "WebFetch", "WebSearch"),
        max_turns=settings.claude_compose_max_turns,
        max_budget_usd=settings.claude_compose_budget_usd,
    )
    if result.timed_out:
        raise RuntimeError(f"Генерация новости не уложилась в таймаут. Лог: {result.log_path}")
    if result.exit_code != 0:
        detail = (
            str((result.parsed or {}).get("result") or "").strip()
            or (result.stderr or "").strip()
        )
        raise RuntimeError(f"Claude Code exit {result.exit_code}: {detail}. Лог: {result.log_path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        document = PostDocument.model_validate(data)
    except Exception as exc:
        raise RuntimeError(f"Сгенерированный JSON невалиден: {exc}") from exc

    source_url = str(document.source.url)
    duplicate_id = _duplicate_source_post(db, source_url)
    if duplicate_id is not None:
        raise RuntimeError(
            f"Эта новость уже использована в посте #{duplicate_id}: {source_url}. "
            "Запустите генерацию ещё раз, чтобы выбрать другую новость."
        )

    source = {
        "title": document.source.title,
        "url": source_url,
        "published_at": document.source.published_at,
        "publisher": document.source.publisher,
    }
    generated = {
        name: getattr(document.platforms, name).content
        for name in PLATFORMS
        if enabled[name]
    }
    errors = validate_document(source, document.image_prompt, generated)
    if errors:
        raise RuntimeError("Новость не прошла проверку: " + "; ".join(errors[:6]))

    post.title = document.source.title[:300]
    post.source_title = document.source.title
    post.source_url = source_url
    post.source_publisher = document.source.publisher
    post.source_published_at = datetime.combine(
        document.source.published_at, dt_time.min, tzinfo=timezone.utc
    )
    post.image_prompt = document.image_prompt
    post.image_enabled = True
    platforms = dict(post.platforms or {})
    platforms.update(generated)
    post.platforms = platforms
    post.platforms_enabled = enabled
    post.version += 1
    db.flush()

    asset = images.generate(db, post, job.created_by, (job.payload or {}).get("model"))
    return {
        "title": post.title,
        "publisher": post.source_publisher,
        "source_url": post.source_url,
        "asset_id": asset.id,
        "log": result.log_path,
    }


def process(db: Session, job: Job) -> None:
    try:
        if job.type == "ai_check":
            result = run_ai_check(db, job)
        elif job.type == "generate_image":
            result = run_generate_image(db, job)
        elif job.type == "compose_news":
            result = run_compose_news(db, job)
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
