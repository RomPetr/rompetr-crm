from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from webapp.db import get_db
from webapp.deps import require_user
from webapp.models.content import Post
from webapp.models.support import Ticket
from webapp.models.user import User
from webapp.templating import render

router = APIRouter(tags=["dashboard"], dependencies=[Depends(require_user)])


@router.get("/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db)):
    user: User = request.state.user
    post_count = db.execute(
        select(func.count(Post.id)).where(Post.author_id == user.id)
    ).scalar_one()
    ticket_count = db.execute(
        select(func.count(Ticket.id)).where(Ticket.user_id == user.id, Ticket.status != "closed")
    ).scalar_one()
    return render(
        request,
        "dashboard/index.html",
        user=user,
        post_count=post_count,
        ticket_count=ticket_count,
    )
