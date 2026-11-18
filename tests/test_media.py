from __future__ import annotations

import io

from PIL import Image

from webapp.db import SessionLocal
from webapp.models.user import User
from webapp.services import media, posts


def png(color: tuple[int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(buffer, format="PNG")
    return buffer.getvalue()


def test_latest_saved_image_becomes_primary():
    db = SessionLocal()
    try:
        admin = db.get(User, 0)
        post = posts.create_draft(db, admin, "Primary asset test")
        db.commit()

        first = media.save_bytes(db, post, png((255, 0, 0)), 0)
        db.commit()
        second = media.save_bytes(db, post, png((0, 0, 255)), 0)
        db.commit()
        db.refresh(first)
        db.refresh(second)

        assert first.is_primary is False
        assert second.is_primary is True
        assert media.primary_asset(db, post).id == second.id

        again = media.save_bytes(db, post, png((255, 0, 0)), 0)
        db.commit()
        db.refresh(first)
        db.refresh(second)
        assert again.id == first.id
        assert again.is_primary is True
        assert second.is_primary is False
        assert media.primary_asset(db, post).id == first.id
    finally:
        db.close()
