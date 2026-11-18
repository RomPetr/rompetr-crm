from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from webapp.models.content import Publication
from webapp.models.system import Job

COUNTED_JOB_STATUSES = ("queued", "running", "succeeded")
COUNTED_PUBLICATION_STATUSES = ("published", "manual_pending")


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
