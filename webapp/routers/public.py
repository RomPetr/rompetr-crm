from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from webapp.config import get_settings
from webapp.templating import render

router = APIRouter(tags=["public"])


@router.get("/", response_class=HTMLResponse)
def landing(request: Request) -> HTMLResponse:
    settings = get_settings()
    return render(request, "public/landing.html", settings=settings)
