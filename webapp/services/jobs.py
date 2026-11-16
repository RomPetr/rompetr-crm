from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from webapp.models.content import Post
from webapp.models.system import Job

JOB_TYPES = ("ai_check", "generate_image")


def _key(post: Post, job_type: str, extra: str = "") -> str:
    if job_type == "ai_check":
        return f"{post.public_id}:ai_check:{post.version}"
    digest = hashlib.sha256((post.image_prompt or "").encode()).hexdigest()[:16]
    return f"{post.public_id}:generate_image:{digest}"


def enqueue(
    db: Session,
    job_type: str,
    post: Post,
    *,
    created_by: int | None = None,
    payload: dict | None = None,
    idempotency_key: str | None = None,
) -> Job:
    if job_type not in JOB_TYPES:
        raise ValueError(f"Неизвестный тип задачи: {job_type}")
    key = idempotency_key or _key(post, job_type)
    existing = db.execute(select(Job).where(Job.idempotency_key == key)).scalar_one_or_none()
    if existing is not None and existing.status in {"queued", "running", "succeeded"}:
        return existing
    job = Job(
        public_id=str(uuid.uuid4()),
        type=job_type,
        status="queued",
        post_id=post.id,
        post_version=post.version,
        payload=payload or {},
        idempotency_key=key,
        created_by=created_by,
    )
    db.add(job)
    db.flush()
    return job


def requeue_stale(db: Session, older_than_minutes: int = 15) -> int:
    threshold = datetime.now(timezone.utc) - timedelta(minutes=older_than_minutes)
    result = db.execute(
        update(Job)
        .where(Job.status == "running", Job.locked_at.is_not(None), Job.locked_at < threshold)
        .values(status="queued", locked_by=None, locked_at=None, heartbeat_at=None)
    )
    return result.rowcount or 0


def claim_next(db: Session, worker_id: str) -> Job | None:
    now = datetime.now(timezone.utc)
    stmt = (
        select(Job)
        .where(Job.status == "queued", Job.available_at <= now)
        .order_by(Job.priority.desc(), Job.id)
        .limit(1)
    )
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)
    job = db.execute(stmt).scalar_one_or_none()
    if job is None:
        return None
    job.status = "running"
    job.locked_by = worker_id
    job.locked_at = now
    job.heartbeat_at = now
    job.started_at = now
    job.attempts += 1
    db.flush()
    db.commit()
    return job


def heartbeat(db: Session, job: Job) -> None:
    job.heartbeat_at = datetime.now(timezone.utc)
    db.flush()


def succeed(db: Session, job: Job, *, result: dict | None = None, log_path: str | None = None) -> None:
    job.status = "succeeded"
    job.finished_at = datetime.now(timezone.utc)
    job.exit_code = 0
    job.error = None
    job.log_path = log_path
    if result:
        job.payload = {**(job.payload or {}), "result": result}
    db.flush()


def fail(
    db: Session,
    job: Job,
    error: str,
    *,
    exit_code: int | None = None,
    log_path: str | None = None,
    retry: bool = True,
) -> None:
    job.error = error[:4000]
    job.exit_code = exit_code
    job.log_path = log_path
    if retry and job.attempts < job.max_attempts:
        job.status = "queued"
        job.locked_by = None
        job.locked_at = None
        job.available_at = datetime.now(timezone.utc) + timedelta(seconds=60 * job.attempts)
    else:
        job.status = "failed"
        job.finished_at = datetime.now(timezone.utc)
    db.flush()
