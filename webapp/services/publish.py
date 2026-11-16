from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from webapp.models.content import Post, Publication
from webapp.models.user import User
from webapp.services import media, telegram, vk, x_manual
from webapp.services import posts as posts_service

PLATFORMS = ("vk", "telegram", "x")


@dataclass
class Outcome:
    platform: str
    status: str
    url: str | None = None
    error: str | None = None


def _get_publication(db: Session, post: Post, platform: str) -> Publication:
    publication = db.execute(
        select(Publication).where(
            Publication.post_id == post.id, Publication.platform == platform
        )
    ).scalar_one_or_none()
    if publication is None:
        publication = Publication(
            post_id=post.id,
            platform=platform,
            status="pending",
            idempotency_key=f"{post.public_id}:{platform}:{post.version}",
        )
        db.add(publication)
        db.flush()
    return publication


def publish_post(db: Session, post: Post, actor: User) -> list[Outcome]:
    if post.status not in {"approved", "published"}:
        raise ValueError("Публиковать можно только одобренный пост")

    texts = post.platforms or {}
    enabled = posts_service.enabled_map(post)
    platforms = [name for name in PLATFORMS if enabled.get(name)]
    if not platforms:
        raise ValueError("Не включена ни одна площадка")
    image_path = None
    asset = media.primary_asset(db, post)
    if asset is not None:
        image_path = media.asset_path(asset)

    outcomes: list[Outcome] = []
    for platform in platforms:
        publication = _get_publication(db, post, platform)

        if publication.status in {"published", "manual_pending"}:
            outcomes.append(
                Outcome(platform, publication.status, publication.external_url, publication.last_error)
            )
            continue
        if publication.status == "unknown":
            outcomes.append(
                Outcome(platform, "unknown", publication.external_url, publication.last_error)
            )
            continue

        text = texts.get(platform, "")
        publication.attempts += 1

        if platform == "x":
            publication.status = "manual_pending"
            publication.external_url = x_manual.intent_url(text)
            publication.payload_hash = None
            db.flush()
            outcomes.append(Outcome(platform, "manual_pending", publication.external_url))
            continue

        publication.status = "publishing"
        db.flush()

        if platform == "vk":
            result = vk.publish(text)
        else:
            result = telegram.publish(text, image_path)

        if result.ok:
            publication.status = "published"
            publication.external_id = result.external_id
            publication.external_url = result.url
            publication.published_at = datetime.now(timezone.utc)
            publication.last_error = None
        elif result.unknown:
            publication.status = "unknown"
            publication.last_error = result.error
        else:
            publication.status = "failed"
            publication.last_error = result.error
        db.flush()
        outcomes.append(
            Outcome(platform, publication.status, publication.external_url, publication.last_error)
        )

    if outcomes and all(
        item.status in {"published", "manual_pending"} for item in outcomes
    ):
        post.status = "published"
        post.published_at = datetime.now(timezone.utc)
    db.flush()
    return outcomes
