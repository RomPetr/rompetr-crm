from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from webapp.config import get_settings
from webapp.templating import templates

router = APIRouter(tags=["public"])


@router.get("/", response_class=HTMLResponse)
def landing(request: Request) -> HTMLResponse:
    settings = get_settings()
    return templates.TemplateResponse(
        request=request,
        name="public/landing.html",
        context={"settings": settings},
    )
