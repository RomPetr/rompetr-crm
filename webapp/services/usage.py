from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from webapp.config import Settings
from webapp.models.content import Post, Publication
from webapp.models.system import Job
from webapp.models.user import User

COUNTED_JOB_STATUSES = ("queued", "running", "succeeded")
COUNTED_PUBLICATION_STATUSES = ("published", "manual_pending")


def effective_guest_limits(user: User, settings: Settings) -> tuple[int, int, int]:
    """Per-user override, falling back to the global guest limits."""
    compose = (
        user.guest_compose_limit
        if user.guest_compose_limit is not None
        else settings.guest_compose_limit
    )
    image = (
        user.guest_image_limit
        if user.guest_image_limit is not None
        else settings.guest_image_limit
    )
    publication = (
        user.guest_publication_limit
        if user.guest_publication_limit is not None
        else settings.guest_publication_limit
    )
    return max(0, compose), max(0, image), max(0, publication)


def user_job_count(db: Session, user_id: int, job_type: str) -> int:
    """Count jobs a user actually started (failed attempts don't consume quota)."""
    value = db.scalar(
        select(func.count(Job.id)).where(
            Job.created_by == user_id,
            Job.type == job_type,
            Job.status.in_(COUNTED_JOB_STATUSES),
        )
    )
    return int(value or 0)


def user_publication_count(db: Session, user_id: int) -> int:
    value = db.scalar(
        select(func.count(Post.id)).where(
            Post.author_id == user_id,
            Post.status == "published",
        )
    )
    return int(value or 0)


def post_job_count(db: Session, post_id: int, job_type: str) -> int:
    value = db.scalar(
        select(func.count(Job.id)).where(
            Job.post_id == post_id,
            Job.type == job_type,
            Job.status.in_(COUNTED_JOB_STATUSES),
        )
    )
    return int(value or 0)


def post_publication_count(db: Session, post_id: int) -> int:
    value = db.scalar(
        select(func.count(Publication.id)).where(
            Publication.post_id == post_id,
            Publication.status.in_(COUNTED_PUBLICATION_STATUSES),
        )
    )
    return int(value or 0)
