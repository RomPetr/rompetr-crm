from __future__ import annotations

import hashlib
import io
from pathlib import Path

from fastapi import HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from webapp.config import get_settings
from webapp.models.content import Asset, Post

ALLOWED_FORMATS = {"PNG", "JPEG"}


def _media_root() -> Path:
    return get_settings().media_path


def save_image(db: Session, post: Post, upload: UploadFile, user_id: int | None) -> Asset:
    settings = get_settings()
    limit = settings.max_upload_mb * 1024 * 1024
    raw = upload.file.read(limit + 1)
    if len(raw) > limit:
        raise HTTPException(status_code=413, detail=f"Файл больше {settings.max_upload_mb} МБ")
    if not raw:
        raise HTTPException(status_code=400, detail="Пустой файл")

    return save_bytes(db, post, raw, user_id)


def save_bytes(db: Session, post: Post, raw: bytes, user_id: int | None) -> Asset:
    try:
        Image.open(io.BytesIO(raw)).verify()
        image = Image.open(io.BytesIO(raw))
    except (UnidentifiedImageError, OSError):
        raise HTTPException(status_code=400, detail="Поддерживаются только PNG и JPEG") from None

    if image.format not in ALLOWED_FORMATS:
        raise HTTPException(status_code=400, detail="Поддерживаются только PNG и JPEG")

    if image.mode not in {"RGB", "RGBA"}:
        image = image.convert("RGBA" if "A" in image.getbands() else "RGB")

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    encoded = buffer.getvalue()
    sha = hashlib.sha256(encoded).hexdigest()

    existing = db.execute(
        select(Asset).where(Asset.post_id == post.id, Asset.sha256 == sha)
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    out_dir = _media_root() / "posts" / post.public_id
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{sha[:20]}.png"
    path = out_dir / filename
    if not path.exists():
        path.write_bytes(encoded)

    has_any = db.execute(select(Asset.id).where(Asset.post_id == post.id)).first()
    asset = Asset(
        post_id=post.id,
        kind="image",
        storage_key=f"posts/{post.public_id}/{filename}",
        mime="image/png",
        bytes=len(encoded),
        width=image.width,
        height=image.height,
        sha256=sha,
        is_primary=has_any is None,
        created_by=user_id,
    )
    db.add(asset)
    db.flush()
    return asset


def asset_path(asset: Asset) -> Path:
    root = _media_root().resolve()
    path = (root / asset.storage_key).resolve()
    if root not in path.parents and path != root:
        raise HTTPException(status_code=404)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Файл не найден")
    return path


def primary_asset(db: Session, post: Post) -> Asset | None:
    return db.execute(
        select(Asset).where(Asset.post_id == post.id).order_by(Asset.is_primary.desc(), Asset.id)
    ).scalars().first()
