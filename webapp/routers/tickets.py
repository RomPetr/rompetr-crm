from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from webapp.db import get_db
from webapp.deps import csrf_protect, require_user
from webapp.models.support import Ticket, TicketMessage
from webapp.models.user import User
from webapp.services import audit
from webapp.templating import render

router = APIRouter(
    tags=["tickets"], dependencies=[Depends(csrf_protect), Depends(require_user)]
)


def _get_ticket(db: Session, ticket_id: int, user: User) -> Ticket:
    ticket = db.get(Ticket, ticket_id)
    if ticket is None or ticket.user_id != user.id:
        raise HTTPException(status_code=404)
    return ticket


def _messages(db: Session, ticket: Ticket):
    return db.execute(
        select(TicketMessage, User)
        .join(User, User.id == TicketMessage.author_id, isouter=True)
        .where(TicketMessage.ticket_id == ticket.id, TicketMessage.is_internal.is_(False))
        .order_by(TicketMessage.created_at, TicketMessage.id)
    ).all()


@router.get("/tickets")
def my_tickets(request: Request, db: Session = Depends(get_db)):
    user: User = request.state.user
    tickets = db.execute(
        select(Ticket).where(Ticket.user_id == user.id).order_by(Ticket.created_at.desc())
    ).scalars().all()
    return render(request, "tickets/list.html", tickets=tickets)


@router.get("/tickets/{ticket_id}")
def ticket_detail(ticket_id: int, request: Request, db: Session = Depends(get_db)):
    user: User = request.state.user
    ticket = _get_ticket(db, ticket_id, user)
    return render(
        request,
        "tickets/detail.html",
        ticket=ticket,
        messages=_messages(db, ticket),
        message=request.query_params.get("ok"),
        error=request.query_params.get("error"),
    )


@router.post("/tickets/{ticket_id}/messages")
def reply_to_ticket(
    ticket_id: int,
    request: Request,
    body: str = Form(...),
    db: Session = Depends(get_db),
):
    user: User = request.state.user
    ticket = _get_ticket(db, ticket_id, user)
    if ticket.status == "closed":
        return RedirectResponse(f"/tickets/{ticket.id}?error=closed", status_code=303)
    text = body.strip()
    if not text:
        return RedirectResponse(f"/tickets/{ticket.id}?error=empty", status_code=303)
    db.add(
        TicketMessage(
            ticket_id=ticket.id,
            author_id=user.id,
            body=text[:4000],
            is_internal=False,
        )
    )
    ticket.updated_at = datetime.now(timezone.utc)
    audit.log_action(
        db,
        "ticket.user_reply",
        actor_id=user.id,
        entity_type="ticket",
        entity_id=str(ticket.id),
    )
    db.commit()
    return RedirectResponse(f"/tickets/{ticket.id}?ok=sent", status_code=303)
