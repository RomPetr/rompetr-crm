from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from webapp.config import get_settings
from webapp.db import get_db
from webapp.deps import csrf_protect, require_admin
from webapp.models.content import Post
from webapp.models.support import Ticket, TicketMessage
from webapp.models.system import Job
from webapp.models.user import User
from webapp.services import audit, sessions
from webapp.services import posts as posts_service
from webapp.services import usage as usage_service
from webapp.templating import render

router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(csrf_protect)]
)


def _admin(request: Request) -> User:
    return request.state.user


@router.get("")
def overview(request: Request, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    counts = {
        "users": db.execute(select(func.count(User.id))).scalar_one(),
        "pending": db.execute(
            select(func.count(User.id)).where(User.status == "pending")
        ).scalar_one(),
        "tickets": db.execute(
            select(func.count(Ticket.id)).where(Ticket.status != "closed")
        ).scalar_one(),
        "posts": db.execute(select(func.count(Post.id))).scalar_one(),
        "jobs": db.execute(
            select(func.count(Job.id)).where(Job.status.in_(["queued", "running"]))
        ).scalar_one(),
    }
    return render(request, "admin/index.html", admin=admin, counts=counts)


@router.get("/users")
def users_list(
    request: Request,
    status: str = "",
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    stmt = select(User).order_by(User.id)
    allowed = {"pending", "active", "blocked", "deleted"}
    if status in allowed:
        stmt = stmt.where(User.status == status)
    users = db.execute(stmt).scalars().all()
    settings = get_settings()
    guest_limits = {}
    for user in users:
        if user.role != "guest":
            continue
        compose_limit, image_limit, publication_limit = usage_service.effective_guest_limits(
            user, settings
        )
        guest_limits[user.id] = {
            "compose_limit": compose_limit,
            "image_limit": image_limit,
            "publication_limit": publication_limit,
            "compose_used": usage_service.user_job_count(db, user.id, "compose_news"),
            "image_used": usage_service.user_job_count(db, user.id, "generate_image"),
            "publications_used": usage_service.user_publication_count(db, user.id),
        }
    return render(
        request,
        "admin/users.html",
        admin=admin,
        users=users,
        guest_limits=guest_limits,
        status_filter=status if status in allowed else "",
    )


@router.post("/users/{user_id}/approve")
def approve_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404)
    if user.id == 0:
        raise HTTPException(status_code=400, detail="ID 0 неизменяем")
    user.role = "user"
    user.status = "active"
    for ticket in db.execute(
        select(Ticket).where(Ticket.user_id == user.id, Ticket.status != "closed")
    ).scalars():
        ticket.status = "closed"
        ticket.closed_at = datetime.now(timezone.utc)
    audit.log_action(db, "admin.user_approved", actor_id=admin.id, entity_type="user", entity_id=str(user.id))
    db.commit()
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/users/{user_id}/block")
def block_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404)
    if user.id == 0:
        raise HTTPException(status_code=400, detail="ID 0 неизменяем")
    user.status = "blocked"
    sessions.revoke_user_sessions(db, user.id)
    audit.log_action(db, "admin.user_blocked", actor_id=admin.id, entity_type="user", entity_id=str(user.id))
    db.commit()
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/users/{user_id}/role")
def change_role(
    user_id: int,
    role: str = Form(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    if role not in {"guest", "user", "admin"}:
        raise HTTPException(status_code=400, detail="Неизвестная роль")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404)
    if user.id == 0:
        raise HTTPException(status_code=400, detail="ID 0 неизменяем")
    user.role = role
    audit.log_action(
        db,
        "admin.role_changed",
        actor_id=admin.id,
        entity_type="user",
        entity_id=str(user.id),
        meta={"role": role},
    )
    db.commit()
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/users/{user_id}/limits")
def set_guest_limits(
    user_id: int,
    compose_limit: int = Form(...),
    image_limit: int = Form(...),
    publication_limit: int = Form(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    values = (compose_limit, image_limit, publication_limit)
    if any(value < 0 or value > 1000 for value in values):
        raise HTTPException(status_code=400, detail="Лимиты должны быть от 0 до 1000")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404)
    if user.id == 0 or user.role != "guest":
        raise HTTPException(status_code=400, detail="Лимиты доступны только для guest")
    user.guest_compose_limit = compose_limit
    user.guest_image_limit = image_limit
    user.guest_publication_limit = publication_limit
    audit.log_action(
        db,
        "admin.guest_limits_updated",
        actor_id=admin.id,
        entity_type="user",
        entity_id=str(user.id),
        meta={
            "compose": compose_limit,
            "image": image_limit,
            "publication": publication_limit,
        },
    )
    db.commit()
    return RedirectResponse("/admin/users?ok=limits", status_code=303)


@router.post("/users/{user_id}/revoke-sessions")
def revoke_sessions(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404)
    sessions.revoke_user_sessions(db, user.id)
    audit.log_action(db, "admin.sessions_revoked", actor_id=admin.id, entity_type="user", entity_id=str(user.id))
    db.commit()
    return RedirectResponse("/admin/users", status_code=303)


@router.get("/tickets")
def tickets_list(request: Request, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    tickets = db.execute(
        select(Ticket, User)
        .join(User, User.id == Ticket.user_id)
        .order_by(Ticket.status, Ticket.created_at.desc())
    ).all()
    return render(request, "admin/tickets.html", admin=admin, tickets=tickets)


@router.get("/tickets/{ticket_id}")
def ticket_detail(
    ticket_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404)
    owner = db.get(User, ticket.user_id)
    messages = db.execute(
        select(TicketMessage, User)
        .join(User, User.id == TicketMessage.author_id, isouter=True)
        .where(TicketMessage.ticket_id == ticket.id)
        .order_by(TicketMessage.created_at)
    ).all()
    return render(
        request,
        "admin/ticket_detail.html",
        admin=admin,
        ticket=ticket,
        owner=owner,
        messages=messages,
    )


@router.post("/tickets/{ticket_id}/messages")
def ticket_reply(
    ticket_id: int,
    body: str = Form(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404)
    text = body.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Пустое сообщение")
    db.add(TicketMessage(ticket_id=ticket.id, author_id=admin.id, body=text[:4000]))
    ticket.updated_at = datetime.now(timezone.utc)
    audit.log_action(db, "admin.ticket_reply", actor_id=admin.id, entity_type="ticket", entity_id=str(ticket.id))
    db.commit()
    return RedirectResponse(f"/admin/tickets/{ticket.id}", status_code=303)


@router.post("/tickets/{ticket_id}/status")
def ticket_status(
    ticket_id: int,
    status: str = Form(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    if status not in {"open", "in_progress", "closed"}:
        raise HTTPException(status_code=400, detail="Неизвестный статус тикета")
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404)
    previous = ticket.status
    ticket.status = status
    ticket.closed_at = datetime.now(timezone.utc) if status == "closed" else None
    ticket.updated_at = datetime.now(timezone.utc)
    audit.log_action(
        db,
        "admin.ticket_status_changed",
        actor_id=admin.id,
        entity_type="ticket",
        entity_id=str(ticket.id),
        meta={"from": previous, "to": status},
    )
    db.commit()
    return RedirectResponse(f"/admin/tickets/{ticket.id}", status_code=303)


@router.get("/posts")
def posts_list(request: Request, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    rows = db.execute(
        select(Post, User)
        .join(User, User.id == Post.author_id)
        .order_by(Post.updated_at.desc())
    ).all()
    return render(request, "admin/posts.html", admin=admin, rows=rows)


@router.post("/posts/{post_id}/approve")
def approve_post(
    post_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    post = db.get(Post, post_id)
    if post is None:
        raise HTTPException(status_code=404)
    posts_service.approve(db, post, admin)
    audit.log_action(db, "admin.post_approved", actor_id=admin.id, entity_type="post", entity_id=str(post.id))
    db.commit()
    return RedirectResponse("/admin/posts", status_code=303)


@router.post("/posts/{post_id}/reject")
def reject_post(
    post_id: int,
    reason: str = Form(""),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    post = db.get(Post, post_id)
    if post is None:
        raise HTTPException(status_code=404)
    posts_service.reject(db, post, admin, reason)
    audit.log_action(
        db,
        "admin.post_rejected",
        actor_id=admin.id,
        entity_type="post",
        entity_id=str(post.id),
        meta={"reason": reason[:500]},
    )
    db.commit()
    return RedirectResponse("/admin/posts", status_code=303)


@router.get("/publications")
def publications_list(
    request: Request, db: Session = Depends(get_db), admin: User = Depends(require_admin)
):
    from webapp.models.content import Publication

    rows = db.execute(
        select(Publication, Post)
        .join(Post, Post.id == Publication.post_id)
        .order_by(Publication.updated_at.desc())
    ).all()
    return render(request, "admin/publications.html", admin=admin, rows=rows)


@router.post("/publications/{publication_id}/mark-published")
def mark_publication_published(
    publication_id: int,
    url: str = Form(""),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    from webapp.models.content import Publication

    publication = db.get(Publication, publication_id)
    if publication is None:
        raise HTTPException(status_code=404)
    if publication.platform != "x":
        raise HTTPException(status_code=400, detail="Ручная отметка доступна только для X")
    publication.status = "published"
    publication.external_url = url.strip() or publication.external_url
    publication.published_at = datetime.now(timezone.utc)
    audit.log_action(
        db,
        "admin.x_marked_published",
        actor_id=admin.id,
        entity_type="publication",
        entity_id=str(publication.id),
    )
    db.commit()
    return RedirectResponse("/admin/publications", status_code=303)


@router.get("/jobs")
def jobs_list(request: Request, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    from webapp.models.system import Job

    rows = db.execute(
        select(Job, Post)
        .join(Post, Post.id == Job.post_id, isouter=True)
        .order_by(Job.id.desc())
        .limit(200)
    ).all()
    return render(request, "admin/jobs.html", admin=admin, rows=rows)


@router.post("/jobs/{job_id}/retry")
def retry_job(
    job_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    from webapp.models.system import Job

    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404)
    if job.status not in {"failed", "timeout", "cancelled"}:
        raise HTTPException(status_code=400, detail="Повтор доступен для failed/timeout/cancelled")
    job.status = "queued"
    job.attempts = 0
    job.locked_by = None
    job.locked_at = None
    job.error = None
    job.available_at = datetime.now(timezone.utc)
    audit.log_action(db, "admin.job_retry", actor_id=admin.id, entity_type="job", entity_id=str(job.id))
    db.commit()
    return RedirectResponse("/admin/jobs", status_code=303)


@router.post("/jobs/{job_id}/cancel")
def cancel_job(
    job_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    from webapp.models.system import Job

    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404)
    if job.status != "queued":
        raise HTTPException(status_code=400, detail="Отменить можно только задачу в очереди")
    job.status = "cancelled"
    job.finished_at = datetime.now(timezone.utc)
    audit.log_action(db, "admin.job_cancelled", actor_id=admin.id, entity_type="job", entity_id=str(job.id))
    db.commit()
    return RedirectResponse("/admin/jobs", status_code=303)


@router.get("/publications/{publication_id}/image")
def publication_image(
    publication_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    from fastapi.responses import FileResponse

    from webapp.models.content import Publication
    from webapp.services import media

    publication = db.get(Publication, publication_id)
    if publication is None or publication.platform != "x":
        raise HTTPException(status_code=404)
    post = db.get(Post, publication.post_id)
    asset = media.primary_asset(db, post) if post else None
    if asset is None:
        raise HTTPException(status_code=404, detail="У поста нет изображения")
    path = media.asset_path(asset)
    return FileResponse(path, media_type=asset.mime, filename=f"{post.base_slug}-x.png")


@router.post("/publications/{publication_id}/x-compose")
def open_x_composer(
    publication_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    from webapp.config import ROOT
    from webapp.models.content import Publication
    from webapp.services import media

    publication = db.get(Publication, publication_id)
    if publication is None or publication.platform != "x":
        raise HTTPException(status_code=404)
    post = db.get(Post, publication.post_id)
    if post is None:
        raise HTTPException(status_code=404)
    asset = media.primary_asset(db, post)
    if asset is None:
        return RedirectResponse("/admin/publications?x=no_image", status_code=303)

    script = ROOT / ".mcp-servers" / "x-mcp" / "x_compose.cjs"
    node = shutil.which("node")
    if not script.exists() or node is None:
        return RedirectResponse("/admin/publications?x=unavailable", status_code=303)

    folder = ROOT / "var" / "x-compose" / str(publication.id)
    folder.mkdir(parents=True, exist_ok=True)
    stem = post.base_slug
    json_path = folder / f"{stem}.json"
    image_path = folder / f"{stem}-image-1.png"
    text = (post.platforms or {}).get("x", "")
    json_path.write_text(
        json.dumps({"platforms": {"x": {"content": text}}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    shutil.copy2(media.asset_path(asset), image_path)

    log_path = folder / "composer.log"
    with open(log_path, "w", encoding="utf-8") as log_file:
        subprocess.Popen(
            [node, str(script), str(json_path)],
            cwd=str(script.parent),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
    audit.log_action(
        db,
        "admin.x_composer_opened",
        actor_id=admin.id,
        entity_type="publication",
        entity_id=str(publication.id),
    )
    db.commit()
    return RedirectResponse("/admin/publications?x=opened", status_code=303)
