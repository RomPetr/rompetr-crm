from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _ru_plural(count: int | str, one: str, few: str, many: str) -> str:
    """Русская форма существительного для числа: 1 поиск, 3 поиска, 5 поисков."""
    try:
        n = abs(int(count))
    except (TypeError, ValueError):
        return many
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


templates.env.filters["ru_plural"] = _ru_plural


def render(request: Request, name: str, *, status_code: int = 200, **context):  # type: ignore[no-untyped-def]
    context.setdefault("user", getattr(request.state, "user", None))
    context.setdefault("csrf_token", getattr(request.state, "csrf_token", ""))
    return templates.TemplateResponse(
        request=request, name=name, context=context, status_code=status_code
    )
