from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from webapp.models.content import Post
from webapp.models.user import User
from webapp.schemas.post_document import validate_document

PLATFORMS = ("telegram", "instagram", "x", "tiktok", "vk")


class ConflictError(Exception):
    pass


def _slug(title: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return value[:40] or "post"


def _unique_slug(db: Session, base: str) -> str:
    candidate = base
    index = 2
    while db.execute(select(Post.id).where(Post.base_slug == candidate)).scalar_one_or_none():
        candidate = f"{base}-{index}"
        index += 1
    return candidate


def create_draft(db: Session, author: User, title: str) -> Post:
    now = datetime.now(timezone.utc)
    base = _unique_slug(db, f"{now:%Y-%m-%d-%H%M%S}-{_slug(title or 'post')}")
    post = Post(
        public_id=str(uuid.uuid4()),
        author_id=author.id,
        status="draft",
        title=title.strip()[:300],
        base_slug=base,
        platforms={name: "" for name in PLATFORMS},
        version=1,
    )
    db.add(post)
    db.flush()
    return post


def apply_form(post: Post, data: dict[str, str], expected_version: int) -> None:
    if post.version != expected_version:
        raise ConflictError("Пост изменён в другой вкладке. Обновите страницу.")
    post.title = data.get("title", post.title).strip()[:300]
    post.source_title = data.get("source_title", "")[:500]
    post.source_url = data.get("source_url", "").strip()
    post.source_publisher = data.get("source_publisher", "").strip()[:64]
    raw_date = data.get("source_published_at", "").strip()
    post.source_published_at = None
    if raw_date:
        try:
            post.source_published_at = datetime.combine(
                date.fromisoformat(raw_date), datetime.min.time(), tzinfo=timezone.utc
            )
        except ValueError:
            post.source_published_at = None
    post.image_prompt = data.get("image_prompt", "")
    platforms = dict(post.platforms or {})
    for name in PLATFORMS:
        platforms[name] = data.get(name, platforms.get(name, ""))
    post.platforms = platforms
    post.version += 1
    post.updated_at = datetime.now(timezone.utc)


def document_parts(post: Post) -> tuple[dict, str, dict[str, str]]:
    source = {
        "title": post.source_title,
        "url": post.source_url,
        "published_at": post.source_published_at.date() if post.source_published_at else None,
        "publisher": post.source_publisher,
    }
    platforms = {name: (post.platforms or {}).get(name, "") for name in PLATFORMS}
    return source, post.image_prompt, platforms


def validate_post(post: Post) -> list[str]:
    source, prompt, platforms = document_parts(post)
    missing = [name for name, text in platforms.items() if not text.strip()]
    errors = [f"{name}: пустой текст" for name in missing]
    if not post.source_title.strip():
        errors.append("source.title: заполните заголовок источника")
    if not post.source_url.strip():
        errors.append("source.url: заполните ссылку")
    if not post.source_publisher.strip():
        errors.append("source.publisher: выберите источник")
    if post.source_published_at is None:
        errors.append("source.published_at: укажите дату публикации")
    if errors:
        return errors
    return validate_document(source, prompt, platforms)


def submit_for_review(db: Session, post: Post) -> list[str]:
    errors = validate_post(post)
    if errors:
        return errors
    post.status = "pending_review"
    post.updated_at = datetime.now(timezone.utc)
    db.flush()
    return []


def approve(db: Session, post: Post, admin: User) -> None:
    post.status = "approved"
    post.approved_by = admin.id
    post.approved_at = datetime.now(timezone.utc)
    post.rejection_reason = None
    post.updated_at = datetime.now(timezone.utc)


def reject(db: Session, post: Post, admin: User, reason: str) -> None:
    post.status = "rejected"
    post.approved_by = admin.id
    post.approved_at = datetime.now(timezone.utc)
    post.rejection_reason = reason.strip()[:2000]
    post.updated_at = datetime.now(timezone.utc)


def can_edit(post: Post, user: User) -> bool:
    if user.role == "admin":
        return True
    return post.author_id == user.id and post.status in {"draft", "rejected"}


def can_view(post: Post, user: User) -> bool:
    return user.role == "admin" or post.author_id == user.id
