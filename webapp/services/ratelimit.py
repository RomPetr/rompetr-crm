from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from webapp.models.system import RateLimit

_SPEC = re.compile(r"^(\d+)\s*/\s*(min|hour|day)$", re.IGNORECASE)
_WINDOWS = {"min": 60, "hour": 3600, "day": 86400}


def parse_spec(spec: str) -> tuple[int, int]:
    match = _SPEC.match(spec.strip())
    if not match:
        raise ValueError(f"Некорректный rate limit: {spec}")
    return int(match.group(1)), _WINDOWS[match.group(2).lower()]


def hit(db: Session, bucket: str, spec: str) -> None:
    limit, seconds = parse_spec(spec)
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(seconds=int(now.timestamp()) % seconds)

    row = db.execute(
        select(RateLimit).where(
            RateLimit.bucket_key == bucket, RateLimit.window_start == window_start
        )
    ).scalar_one_or_none()

    if row is None:
        db.add(RateLimit(bucket_key=bucket, window_start=window_start, count=1))
        db.flush()
        return

    if row.count >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Слишком много попыток. Попробуйте позже.",
        )
    row.count += 1
    db.flush()
