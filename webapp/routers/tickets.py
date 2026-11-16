from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from webapp.db import get_db
from webapp.deps import require_user
from webapp.models.support import Ticket
from webapp.models.user import User
from webapp.templating import render

router = APIRouter(tags=["tickets"], dependencies=[Depends(require_user)])


@router.get("/tickets")
def my_tickets(request: Request, db: Session = Depends(get_db)):
    user: User = request.state.user
    tickets = db.execute(
        select(Ticket).where(Ticket.user_id == user.id).order_by(Ticket.created_at.desc())
    ).scalars().all()
    return render(request, "tickets/list.html", tickets=tickets)
