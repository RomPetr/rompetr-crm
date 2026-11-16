from __future__ import annotations

from datetime import datetime, timedelta, timezone

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from webapp.config import get_settings
from webapp.db import get_db
from webapp.deps import csrf_protect, current_user
from webapp.models.user import User
from webapp.services import audit, email, ratelimit, sessions, users
from webapp.services.security import verify_password
from webapp.templating import render

router = APIRouter(tags=["auth"], dependencies=[Depends(csrf_protect)])


def _set_session_cookie(response, token: str):  # type: ignore[no-untyped-def]
    settings = get_settings()
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_ttl_days * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    return response


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.get("/login")
def login_form(request: Request, verified: int = 0, reset: int = 0):
    if current_user(request) is not None:
        return RedirectResponse("/dashboard", status_code=303)
    return render(
        request,
        "auth/login.html",
        verified=bool(verified),
        reset=bool(reset),
    )


@router.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    ip = _client_ip(request)
    try:
        ratelimit.hit(db, f"login:{ip}", settings.rate_limit_login)
        db.commit()
    except Exception:
        db.rollback()
        raise

    user = users.find_by_login_or_email(db, username)
    error = "Неверный логин или пароль."

    if user is None or not verify_password(user.password_hash, password):
        if user is not None:
            user.failed_login_count += 1
            if user.failed_login_count >= 10:
                user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=15)
                user.failed_login_count = 0
            audit.log_action(
                db,
                "auth.login_failed",
                actor_id=user.id,
                ip=ip,
                user_agent=request.headers.get("user-agent"),
            )
            db.commit()
        return render(request, "auth/login.html", status_code=400, error=error, username=username)

    if user.status == "blocked":
        return render(request, "auth/login.html", status_code=403, error="Аккаунт заблокирован.", username=username)
    if user.status == "pending":
        return render(
            request,
            "auth/login.html",
            status_code=403,
            error="Подтвердите e-mail, чтобы войти.",
            username=username,
        )
    if user.status != "active":
        return render(request, "auth/login.html", status_code=400, error=error, username=username)

    locked_until = user.locked_until
    if locked_until is not None and locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=timezone.utc)
    if locked_until and locked_until > datetime.now(timezone.utc):
        return render(
            request,
            "auth/login.html",
            status_code=429,
            error="Вход временно заблокирован. Попробуйте позже.",
            username=username,
        )

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = datetime.now(timezone.utc)
    token = sessions.create_session(
        db, user, ip=ip, user_agent=request.headers.get("user-agent")
    )
    audit.log_action(db, "auth.login", actor_id=user.id, ip=ip)
    db.commit()

    response = RedirectResponse("/dashboard", status_code=303)
    return _set_session_cookie(response, token)


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    session = getattr(request.state, "session", None)
    if session is not None:
        sessions.revoke_session(db, session)
        audit.log_action(db, "auth.logout", actor_id=session.user_id)
        db.commit()
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(get_settings().session_cookie_name, path="/")
    return response


@router.get("/register")
def register_form(request: Request):
    if current_user(request) is not None:
        return RedirectResponse("/dashboard", status_code=303)
    return render(request, "auth/register.html")


@router.post("/register")
def register(
    request: Request,
    login_name: str = Form(..., alias="login"),
    email_addr: str = Form(..., alias="email"),
    password: str = Form(...),
    password_confirm: str = Form(...),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    ip = _client_ip(request)
    errors: list[str] = []

    login_value = users.normalize_login(login_name)
    if not users.LOGIN_RE.match(login_value):
        errors.append("Логин: 3–32 символа, только латиница в нижнем регистре, цифры и _.")
    try:
        email_value = validate_email(email_addr, check_deliverability=False).normalized
    except EmailNotValidError:
        email_value = ""
        errors.append("Введите корректный e-mail.")
    if len(password) < users.PASSWORD_MIN:
        errors.append(f"Пароль должен быть не короче {users.PASSWORD_MIN} символов.")
    if password != password_confirm:
        errors.append("Пароли не совпадают.")

    if not errors:
        exists = db.execute(
            select(User).where((User.login == login_value) | (User.email == email_value))
        ).scalar_one_or_none()
        if exists:
            errors.append("Пользователь с таким логином или e-mail уже существует.")
        try:
            ratelimit.hit(db, f"register:{ip}", settings.rate_limit_register)
        except Exception:
            db.rollback()
            return render(
                request,
                "auth/register.html",
                status_code=429,
                errors=["Слишком много регистраций. Попробуйте позже."],
                login=login_name,
                email=email_addr,
            )

    if errors:
        return render(
            request,
            "auth/register.html",
            status_code=400,
            errors=errors,
            login=login_name,
            email=email_addr,
        )

    user, token = users.create_user(
        db, login=login_value, email=email_value, password=password
    )
    link = email.verification_link(token)
    email.enqueue_email(
        db,
        user.email,
        "Подтверждение регистрации",
        email.mail_body("Здравствуйте!", "Подтвердите e-mail перейдя по ссылке:", link),
    )
    audit.log_action(db, "user.register", actor_id=user.id, ip=ip)
    db.commit()

    show_link = settings.email_mode in {"dev", "file"}
    return render(
        request,
        "auth/register.html",
        done=True,
        dev_link=link if show_link else None,
        login=login_value,
    )


@router.get("/verify")
def verify(request: Request, token: str = "", db: Session = Depends(get_db)):
    if not token:
        return render(request, "auth/verify.html", ok=False, message="Ссылка неполная.")
    user = users.consume_token(db, token, "verify_email")
    if user is None:
        return render(request, "auth/verify.html", ok=False, message="Ссылка недействительна или истекла.")
    users.activate_user(db, user)
    audit.log_action(db, "user.verify", actor_id=user.id, ip=_client_ip(request))
    db.commit()
    return render(request, "auth/verify.html", ok=True, message="E-mail подтверждён. Теперь можно войти.")


@router.get("/verify/resend")
def verify_resend_form(request: Request):
    return render(request, "auth/verify.html", ok=False, message="Введите e-mail в форме восстановления пароля.")


@router.get("/forgot-password")
def forgot_form(request: Request):
    return render(request, "auth/forgot.html")


@router.post("/forgot-password")
def forgot(
    request: Request,
    email_addr: str = Form(..., alias="email"),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    ip = _client_ip(request)
    try:
        ratelimit.hit(db, f"reset:{ip}", settings.rate_limit_reset)
    except Exception:
        db.rollback()
        return render(request, "auth/forgot.html", sent=True)

    user = db.execute(select(User).where(User.email == email_addr.strip().lower())).scalar_one_or_none()
    if user is not None and user.status == "active":
        token = users.issue_reset_token(db, user)
        link = email.reset_link(token)
        email.enqueue_email(
            db,
            user.email,
            "Сброс пароля",
            email.mail_body("Сброс пароля", "Установите новый пароль по ссылке:", link),
        )
        audit.log_action(db, "user.reset_requested", actor_id=user.id, ip=ip)
    db.commit()
    return render(request, "auth/forgot.html", sent=True)


@router.get("/reset-password")
def reset_form(request: Request, token: str = ""):
    return render(request, "auth/reset.html", token=token)


@router.post("/reset-password")
def reset(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    db: Session = Depends(get_db),
):
    if len(password) < users.PASSWORD_MIN:
        return render(request, "auth/reset.html", status_code=400, token=token, error="Пароль слишком короткий.")
    if password != password_confirm:
        return render(request, "auth/reset.html", status_code=400, token=token, error="Пароли не совпадают.")

    user = users.consume_token(db, token, "reset_password")
    if user is None:
        return render(
            request,
            "auth/reset.html",
            status_code=400,
            token=token,
            error="Ссылка недействительна или истекла.",
        )

    users.set_password(db, user, password)
    sessions.revoke_user_sessions(db, user.id)
    audit.log_action(db, "user.password_reset", actor_id=user.id, ip=_client_ip(request))
    db.commit()
    return RedirectResponse("/login?reset=1", status_code=303)
