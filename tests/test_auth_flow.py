from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EMAIL = "guest@example.com"


def csrf(client) -> str:
    client.get("/login")
    return client.cookies.get("csrf_token")


def latest_mail() -> str:
    files = sorted((ROOT / "var" / "mail").glob("*.txt"), key=lambda p: p.stat().st_mtime)
    assert files, "no mail written"
    return files[-1].read_text(encoding="utf-8")


def test_csrf_required(client):
    response = client.post("/login", data={"username": "admin", "password": "x"})
    assert response.status_code == 403


def test_register_verify_login_and_approve(client):
    token = csrf(client)
    response = client.post(
        "/register",
        data={
            "csrf_token": token,
            "login": "guest",
            "email": EMAIL,
            "password": "guest-password-123",
            "password_confirm": "guest-password-123",
        },
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert "Проверьте почту" in response.text

    mail = latest_mail()
    match = re.search(r"/verify\?token=([A-Za-z0-9_-]+)", mail)
    assert match, mail

    verified = client.get(f"/verify?token={match.group(1)}")
    assert verified.status_code == 200
    assert "E-mail подтверждён" in verified.text

    token = csrf(client)
    login = client.post(
        "/login",
        data={"csrf_token": token, "username": "guest", "password": "guest-password-123"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert login.headers["location"] == "/dashboard"

    dashboard = client.get("/dashboard")
    assert dashboard.status_code == 200
    assert "роль: guest" in dashboard.text

    published = client.post("/drafts/1/publish", data={"csrf_token": token})
    assert published.status_code in {400, 403, 404, 405}

    client.post("/logout", data={"csrf_token": token})

    admin_token = csrf(client)
    admin_login = client.post(
        "/login",
        data={"csrf_token": admin_token, "username": "admin", "password": "test-admin-password-12345"},
        follow_redirects=False,
    )
    assert admin_login.status_code == 303

    users_page = client.get("/admin/users")
    assert users_page.status_code == 200
    assert "guest" in users_page.text
    assert "Сделать пользователем" in users_page.text
    approved = client.post(
        "/admin/users/1/approve", data={"csrf_token": admin_token}, follow_redirects=False
    )
    assert approved.status_code == 303

    users_after = client.get("/admin/users")
    assert "user" in users_after.text


def test_admin_id_zero_is_protected_in_ui(client):
    page = client.get("/admin/users")
    assert page.status_code == 200
    assert "защищён" in page.text


def test_admin_dashboard_links_and_user_filter(client):
    token = csrf(client)
    login = client.post(
        "/login",
        data={"csrf_token": token, "username": "admin", "password": "test-admin-password-12345"},
        follow_redirects=False,
    )
    assert login.status_code == 303

    page = client.get("/admin")
    assert page.status_code == 200
    assert 'href="/admin/users"' in page.text
    assert 'href="/admin/users?status=pending"' in page.text
    assert 'href="/admin/tickets"' in page.text
    assert 'href="/admin/posts"' in page.text
    assert 'href="/admin/jobs"' in page.text

    users = client.get("/admin/users?status=pending")
    assert users.status_code == 200
    assert "Фильтр: статус" in users.text
    assert "Имя / логин" in users.text
