from __future__ import annotations

import secrets

from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from webapp.config import get_settings
from webapp.db import SessionLocal
from webapp.services.sessions import touch_session, user_for_token

CSRF_COOKIE = "csrf_token"

CSP = (
    "default-src 'self'; "
    "base-uri 'self'; "
    "img-src 'self' data:; "
    "style-src 'self'; "
    "script-src 'self'; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        response.headers.setdefault("Content-Security-Policy", CSP)
        if get_settings().is_prod:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response


class AuthContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        settings = get_settings()
        request.state.user = None
        request.state.session = None

        if not request.url.path.startswith("/static/"):
            token = request.cookies.get(settings.session_cookie_name)
            if token:
                db = SessionLocal()
                try:
                    pair = user_for_token(db, token)
                    if pair is not None:
                        user, session = pair
                        touch_session(db, session)
                        db.commit()
                        request.state.user = user
                        request.state.session = session
                except SQLAlchemyError:
                    db.rollback()
                finally:
                    db.close()

        csrf_token = request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(32)
        request.state.csrf_token = csrf_token

        response = await call_next(request)
        if CSRF_COOKIE not in request.cookies:
            response.set_cookie(
                CSRF_COOKIE,
                csrf_token,
                max_age=60 * 60 * 24 * 30,
                httponly=True,
                samesite="lax",
                secure=settings.cookie_secure,
            )
        return response
