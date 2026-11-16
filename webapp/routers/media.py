from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from webapp.db import get_db
from webapp.deps import require_user
from webapp.models.content import Asset, Post
from webapp.models.user import User
from webapp.services import media, posts

router = APIRouter(tags=["media"], dependencies=[Depends(require_user)])


@router.get("/media/{public_id}/{filename}")
def media_file(public_id: str, filename: str, request: Request, db: Session = Depends(get_db)):
    user: User = request.state.user
    post = db.execute(select(Post).where(Post.public_id == public_id)).scalar_one_or_none()
    if post is None or not posts.can_view(post, user):
        raise HTTPException(status_code=404)
    asset = db.execute(
        select(Asset).where(Asset.post_id == post.id, Asset.storage_key.endswith(filename))
    ).scalars().first()
    if asset is None:
        raise HTTPException(status_code=404)
    path = media.asset_path(asset)
    return FileResponse(path, media_type=asset.mime, filename=path.name)
