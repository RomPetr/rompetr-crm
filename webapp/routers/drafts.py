from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from webapp.db import get_db
from webapp.deps import csrf_protect, require_user
from webapp.models.content import Asset, Post, Publication
from webapp.models.system import Job
from webapp.models.user import User
from webapp.services import audit, jobs, media, posts
from webapp.services import publish as publish_service
from webapp.templating import render

router = APIRouter(
    tags=["drafts"], dependencies=[Depends(csrf_protect), Depends(require_user)]
)


def _get_post(db: Session, post_id: int, user: User) -> Post:
    post = db.get(Post, post_id)
    if post is None or not posts.can_view(post, user):
        raise HTTPException(status_code=404)
    return post


def _values(post: Post) -> dict:
    return {
        "title": post.title,
        "source_title": post.source_title,
        "source_url": post.source_url,
        "source_publisher": post.source_publisher,
        "source_published_at": (
            post.source_published_at.date().isoformat() if post.source_published_at else ""
        ),
        "image_prompt": post.image_prompt,
        "image_enabled": post.image_enabled,
        **(post.platforms or {}),
        **{f"enabled_{name}": value for name, value in posts.enabled_map(post).items()},
    }


@router.get("/drafts")
def list_drafts(request: Request, db: Session = Depends(get_db)):
    user: User = request.state.user
    stmt = (
        select(Post, User)
        .join(User, User.id == Post.author_id)
        .order_by(Post.updated_at.desc())
    )
    if user.role != "admin":
        stmt = stmt.where(Post.author_id == user.id)
    items = db.execute(stmt).all()
    return render(request, "drafts/list.html", items=items)


@router.get("/drafts/new")
def new_draft_form(request: Request):
    return render(request, "drafts/new.html")


@router.post("/drafts/new")
async def create_draft(request: Request, db: Session = Depends(get_db)):
    user: User = request.state.user
    form = await request.form()
    title = str(form.get("title", "")).strip()
    if not title:
        return render(request, "drafts/new.html", error="Укажите название черновика", title=title)
    post = posts.create_draft(db, user, title)
    audit.log_action(db, "post.created", actor_id=user.id, entity_type="post", entity_id=str(post.id))
    db.commit()
    return RedirectResponse(f"/drafts/{post.id}", status_code=303)


@router.get("/drafts/{post_id}")
def edit_draft(post_id: int, request: Request, db: Session = Depends(get_db)):
    user: User = request.state.user
    post = _get_post(db, post_id, user)
    asset = media.primary_asset(db, post)
    moderator = db.get(User, post.approved_by) if post.approved_by is not None else None
    active_job = None
    completed_job = None
    raw_job = request.query_params.get("job", "")
    if raw_job.isdigit():
        job = db.get(Job, int(raw_job))
        if job is not None and job.post_id == post.id:
            if job.status in {"queued", "running"}:
                active_job = job
            else:
                completed_job = job
    publications = db.execute(
        select(Publication).where(Publication.post_id == post.id).order_by(Publication.platform)
    ).scalars().all()
    return render(
        request,
        "drafts/edit.html",
        post=post,
        values=_values(post),
        asset=asset,
        publications=publications,
        moderator=moderator,
        active_job=active_job,
        completed_job=completed_job,
        editable=posts.can_edit(post, user),
        message=request.query_params.get("ok"),
        error=request.query_params.get("error"),
    )


@router.post("/drafts/{post_id}")
async def save_draft(post_id: int, request: Request, db: Session = Depends(get_db)):
    user: User = request.state.user
    post = _get_post(db, post_id, user)
    if not posts.can_edit(post, user):
        raise HTTPException(status_code=403, detail="Редактирование недоступно")
    form = await request.form()
    data = {key: str(value) for key, value in form.items() if isinstance(value, str)}
    try:
        posts.apply_form(post, data, int(data.get("version", "0")))
    except (posts.ConflictError, ValueError) as exc:
        db.rollback()
        return RedirectResponse(f"/drafts/{post_id}?error={str(exc)}", status_code=303)
    audit.log_action(db, "post.saved", actor_id=user.id, entity_type="post", entity_id=str(post.id))
    db.commit()
    return RedirectResponse(f"/drafts/{post_id}?ok=saved", status_code=303)


@router.post("/drafts/{post_id}/check")
def check_draft(post_id: int, request: Request, db: Session = Depends(get_db)):
    user: User = request.state.user
    post = _get_post(db, post_id, user)
    errors = posts.validate_post(post)
    if errors:
        return render(
            request,
            "drafts/edit.html",
            post=post,
            values=_values(post),
            asset=media.primary_asset(db, post),
            editable=posts.can_edit(post, user),
            check_errors=errors,
        )
    return RedirectResponse(f"/drafts/{post_id}?ok=check", status_code=303)


@router.post("/drafts/{post_id}/submit")
def submit_draft(post_id: int, request: Request, db: Session = Depends(get_db)):
    user: User = request.state.user
    post = _get_post(db, post_id, user)
    if not posts.can_edit(post, user):
        raise HTTPException(status_code=403)
    errors = posts.submit_for_review(db, post)
    if errors:
        return render(
            request,
            "drafts/edit.html",
            post=post,
            values=_values(post),
            asset=media.primary_asset(db, post),
            editable=True,
            check_errors=errors,
        )
    audit.log_action(db, "post.submitted", actor_id=user.id, entity_type="post", entity_id=str(post.id))
    db.commit()
    return RedirectResponse(f"/drafts/{post_id}?ok=submitted", status_code=303)


@router.post("/drafts/{post_id}/assets")
async def upload_asset(post_id: int, request: Request, db: Session = Depends(get_db)):
    user: User = request.state.user
    post = _get_post(db, post_id, user)
    if not posts.can_edit(post, user):
        raise HTTPException(status_code=403)
    form = await request.form()
    upload = form.get("image")
    if upload is None or not hasattr(upload, "file"):
        return RedirectResponse(f"/drafts/{post_id}?error=Файл не выбран", status_code=303)
    try:
        asset = media.save_image(db, post, upload, user.id)
    except HTTPException as exc:
        db.rollback()
        return RedirectResponse(f"/drafts/{post_id}?error={exc.detail}", status_code=303)
    audit.log_action(
        db,
        "post.asset_uploaded",
        actor_id=user.id,
        entity_type="post",
        entity_id=str(post.id),
        meta={"asset_id": asset.id},
    )
    db.commit()
    return RedirectResponse(f"/drafts/{post_id}?ok=image", status_code=303)


@router.post("/drafts/{post_id}/assets/{asset_id}/delete")
def delete_asset(post_id: int, asset_id: int, request: Request, db: Session = Depends(get_db)):
    user: User = request.state.user
    post = _get_post(db, post_id, user)
    if not posts.can_edit(post, user):
        raise HTTPException(status_code=403)
    asset = db.get(Asset, asset_id)
    if asset is None or asset.post_id != post.id:
        raise HTTPException(status_code=404)
    db.delete(asset)
    audit.log_action(db, "post.asset_deleted", actor_id=user.id, entity_type="post", entity_id=str(post.id))
    db.commit()
    return RedirectResponse(f"/drafts/{post_id}?ok=image_deleted", status_code=303)


@router.post("/drafts/{post_id}/publish")
def publish_now(post_id: int, request: Request, db: Session = Depends(get_db)):
    user: User = request.state.user
    post = _get_post(db, post_id, user)
    if user.role == "guest":
        raise HTTPException(status_code=403, detail="Гостевой доступ не позволяет публиковать")
    if post.status not in {"approved", "published"}:
        raise HTTPException(status_code=400, detail="Публикация доступна только для одобренного поста")
    try:
        outcomes = publish_service.publish_post(db, post, user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    audit.log_action(
        db,
        "post.published",
        actor_id=user.id,
        entity_type="post",
        entity_id=str(post.id),
        meta={item.platform: item.status for item in outcomes},
    )
    db.commit()
    failed = [item.platform for item in outcomes if item.status in {"failed", "unknown"}]
    if failed:
        return RedirectResponse(
            f"/drafts/{post_id}?error=Не удалось опубликовать: {', '.join(failed)}",
            status_code=303,
        )
    return RedirectResponse(f"/drafts/{post_id}?ok=published", status_code=303)


@router.post("/drafts/{post_id}/archive")
def archive_draft(post_id: int, request: Request, db: Session = Depends(get_db)):
    user: User = request.state.user
    post = _get_post(db, post_id, user)
    if not posts.can_edit(post, user):
        raise HTTPException(status_code=403)
    post.status = "archived"
    audit.log_action(db, "post.archived", actor_id=user.id, entity_type="post", entity_id=str(post.id))
    db.commit()
    return RedirectResponse("/drafts", status_code=303)


@router.post("/drafts/{post_id}/ai-check")
def enqueue_ai_check(post_id: int, request: Request, db: Session = Depends(get_db)):
    user: User = request.state.user
    post = _get_post(db, post_id, user)
    if not posts.can_edit(post, user):
        raise HTTPException(status_code=403)
    job = jobs.enqueue(db, "ai_check", post, created_by=user.id)
    audit.log_action(db, "post.ai_check_queued", actor_id=user.id, entity_type="post", entity_id=str(post.id))
    db.commit()
    return RedirectResponse(f"/drafts/{post_id}?ok=queued_ai&job={job.id}", status_code=303)


@router.post("/drafts/{post_id}/generate-image")
def enqueue_generate_image(
    post_id: int,
    request: Request,
    model: str = Form(""),
    db: Session = Depends(get_db),
):
    from webapp.services.images import IMAGE_MODELS

    user: User = request.state.user
    post = _get_post(db, post_id, user)
    if not posts.can_edit(post, user):
        raise HTTPException(status_code=403)
    if not post.image_enabled:
        raise HTTPException(status_code=400, detail="Сначала включите image_prompt")
    selected = model if model in IMAGE_MODELS else IMAGE_MODELS[0]
    job = jobs.enqueue(
        db, "generate_image", post, created_by=user.id, payload={"model": selected}
    )
    audit.log_action(
        db,
        "post.image_queued",
        actor_id=user.id,
        entity_type="post",
        entity_id=str(post.id),
        meta={"model": selected},
    )
    db.commit()
    return RedirectResponse(f"/drafts/{post_id}?ok=queued_image&job={job.id}", status_code=303)


@router.get("/drafts/{post_id}/jobs/{job_id}/status")
def job_status(post_id: int, job_id: int, request: Request, db: Session = Depends(get_db)):
    user: User = request.state.user
    post = _get_post(db, post_id, user)
    job = db.get(Job, job_id)
    if job is None or job.post_id != post.id:
        raise HTTPException(status_code=404)
    return JSONResponse({"id": job.id, "type": job.type, "status": job.status})


@router.get("/drafts/{post_id}/assets/{asset_id}/download")
def download_asset(post_id: int, asset_id: int, request: Request, db: Session = Depends(get_db)):
    user: User = request.state.user
    post = _get_post(db, post_id, user)
    asset = db.get(Asset, asset_id)
    if asset is None or asset.post_id != post.id:
        raise HTTPException(status_code=404)
    path = media.asset_path(asset)
    filename = f"{post.base_slug}-image-{asset.id}.png"
    return FileResponse(path, media_type=asset.mime, filename=filename)
