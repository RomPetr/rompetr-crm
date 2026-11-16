from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from webapp.models.content import Post
from webapp.services import audit, publish


def publish_due(db: Session, now: datetime | None = None) -> list[tuple[int, list[publish.Outcome]]]:
    moment = now or datetime.now(timezone.utc)
    due = db.execute(
        select(Post).where(
            Post.status == "approved",
            Post.scheduled_at.is_not(None),
            Post.scheduled_at <= moment,
        )
    ).scalars().all()

    results: list[tuple[int, list[publish.Outcome]]] = []
    for post in due:
        outcomes = publish.publish_post(db, post, _system_actor(db))
        audit.log_action(
            db,
            "post.scheduled_publish",
            entity_type="post",
            entity_id=str(post.id),
            meta={item.platform: item.status for item in outcomes},
        )
        db.commit()
        results.append((post.id, outcomes))
    return results


def _system_actor(db: Session):
    from webapp.models.user import User

    return db.get(User, 0)
