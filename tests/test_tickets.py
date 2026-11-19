from __future__ import annotations

from datetime import datetime, timezone

from webapp.db import SessionLocal
from webapp.models.support import Ticket, TicketMessage
from webapp.models.user import User
from webapp.services.security import hash_password

SUBJECT = "Проверка переписки по тикету"


def csrf(client) -> str:
    client.get("/login")
    return client.cookies.get("csrf_token")


def login(client, username: str, password: str) -> None:
    token = csrf(client)
    response = client.post(
        "/login",
        data={"csrf_token": token, "username": username, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text


def _ensure_user(db, login_name: str, password: str) -> User:
    user = db.query(User).filter(User.login == login_name).first()
    if user is None:
        user = User(
            login=login_name,
            email=f"{login_name}@example.com",
            password_hash=hash_password(password),
            role="guest",
            status="active",
        )
        db.add(user)
        db.flush()
    return user


def _ensure_ticket() -> int:
    db = SessionLocal()
    try:
        owner = _ensure_user(db, "ticket_owner", "ticket-owner-password-123")
        _ensure_user(db, "ticket_reader", "ticket-reader-password-123")
        ticket = (
            db.query(Ticket)
            .filter(Ticket.user_id == owner.id, Ticket.subject == SUBJECT)
            .first()
        )
        if ticket is None:
            now = datetime.now(timezone.utc)
            ticket = Ticket(
                user_id=owner.id,
                kind="support",
                subject=SUBJECT,
                status="open",
                created_at=now,
                updated_at=now,
            )
            db.add(ticket)
            db.flush()
            db.add(
                TicketMessage(
                    ticket_id=ticket.id,
                    author_id=owner.id,
                    body="Исходное сообщение пользователя.",
                    created_at=now,
                )
            )
            db.add(
                TicketMessage(
                    ticket_id=ticket.id,
                    author_id=0,
                    body="Ответ администратора.",
                    created_at=now,
                )
            )
            db.add(
                TicketMessage(
                    ticket_id=ticket.id,
                    author_id=None,
                    body="Внутренняя заметка администратора.",
                    is_internal=True,
                    created_at=now,
                )
            )
            db.commit()
        else:
            ticket.status = "open"
            ticket.closed_at = None
            db.commit()
        return ticket.id
    finally:
        db.close()


def test_ticket_detail_and_user_reply(client):
    ticket_id = _ensure_ticket()

    login(client, "ticket_owner", "ticket-owner-password-123")
    listing = client.get("/tickets")
    assert f'href="/tickets/{ticket_id}"' in listing.text

    page = client.get(f"/tickets/{ticket_id}")
    assert page.status_code == 200
    assert "Исходное сообщение пользователя." in page.text
    assert "Ответ администратора." in page.text
    assert "Внутренняя заметка администратора." not in page.text
    assert f'action="/tickets/{ticket_id}/messages"' in page.text

    token = csrf(client)
    reply = client.post(
        f"/tickets/{ticket_id}/messages",
        data={"csrf_token": token, "body": "Ответ пользователя по тикету."},
        follow_redirects=False,
    )
    assert reply.status_code == 303
    assert reply.headers["location"] == f"/tickets/{ticket_id}?ok=sent"

    after = client.get(reply.headers["location"])
    assert "Ответ пользователя по тикету." in after.text
    assert "Сообщение отправлено." in after.text

    empty = client.post(
        f"/tickets/{ticket_id}/messages",
        data={"csrf_token": token, "body": "   "},
        follow_redirects=False,
    )
    assert empty.status_code == 303
    assert empty.headers["location"] == f"/tickets/{ticket_id}?error=empty"

    login(client, "ticket_reader", "ticket-reader-password-123")
    assert client.get(f"/tickets/{ticket_id}").status_code == 404
    denied = client.post(
        f"/tickets/{ticket_id}/messages",
        data={"csrf_token": csrf(client), "body": "Чужой ответ."},
        follow_redirects=False,
    )
    assert denied.status_code == 404

    db = SessionLocal()
    try:
        ticket = db.get(Ticket, ticket_id)
        ticket.status = "closed"
        ticket.closed_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()

    login(client, "ticket_owner", "ticket-owner-password-123")
    closed_page = client.get(f"/tickets/{ticket_id}")
    assert "Тикет закрыт." in closed_page.text
    assert f'action="/tickets/{ticket_id}/messages"' not in closed_page.text

    closed_reply = client.post(
        f"/tickets/{ticket_id}/messages",
        data={"csrf_token": csrf(client), "body": "Ответ в закрытый тикет."},
        follow_redirects=False,
    )
    assert closed_reply.status_code == 303
    assert closed_reply.headers["location"] == f"/tickets/{ticket_id}?error=closed"
    assert "ответить на него нельзя" in client.get(closed_reply.headers["location"]).text


def test_admin_can_change_ticket_status(client):
    ticket_id = _ensure_ticket()
    login(client, "admin", "test-admin-password-12345")
    token = csrf(client)

    def change(value: str):
        return client.post(
            f"/admin/tickets/{ticket_id}/status",
            data={"csrf_token": token, "status": value},
            follow_redirects=False,
        )

    in_progress = change("in_progress")
    assert in_progress.status_code == 303
    db = SessionLocal()
    try:
        assert db.get(Ticket, ticket_id).status == "in_progress"
    finally:
        db.close()

    closed = change("closed")
    assert closed.status_code == 303
    db = SessionLocal()
    try:
        ticket = db.get(Ticket, ticket_id)
        assert ticket.status == "closed"
        assert ticket.closed_at is not None
    finally:
        db.close()

    page = client.get(f"/admin/tickets/{ticket_id}")
    assert "Переоткрыть" in page.text
    assert "В работу" not in page.text

    reopened = change("open")
    assert reopened.status_code == 303
    db = SessionLocal()
    try:
        ticket = db.get(Ticket, ticket_id)
        assert ticket.status == "open"
        assert ticket.closed_at is None
    finally:
        db.close()

    assert "В работу" in client.get(f"/admin/tickets/{ticket_id}").text
    assert change("unknown").status_code == 400
