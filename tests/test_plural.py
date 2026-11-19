from __future__ import annotations

from webapp.templating import templates

GUEST_LINE = (
    'Гостю доступно {{ n }} {{ n | ru_plural("поиск", "поиска", "поисков") }} новости.'
)


def render_guest_line(n: int) -> str:
    return templates.env.from_string(GUEST_LINE).render(n=n)


def test_ru_plural_forms():
    assert render_guest_line(1) == "Гостю доступно 1 поиск новости."
    assert render_guest_line(3) == "Гостю доступно 3 поиска новости."
    assert render_guest_line(11) == "Гостю доступно 11 поисков новости."
    assert render_guest_line(21) == "Гостю доступно 21 поиск новости."
    assert render_guest_line(0) == "Гостю доступно 0 поисков новости."
