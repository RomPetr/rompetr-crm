from __future__ import annotations

import pytest
from pydantic import ValidationError

from webapp.schemas.post_document import (
    Platforms,
    PlatformsPartial,
    PostDocument,
    PostDocumentPartial,
)

SOURCE = {
    "title": "1inch добавил поддержку нового протокола",
    "url": "https://www.theblock.co/post/1",
    "published_at": "2026-11-19",
    "publisher": "The Block",
}
PLATFORM_NAMES = ("telegram", "instagram", "x", "tiktok", "vk")


def _plain_platforms(text: str) -> dict[str, str]:
    return {name: text for name in PLATFORM_NAMES}


def _object_platforms(text: str) -> dict[str, dict[str, str]]:
    return {name: {"content": text} for name in PLATFORM_NAMES}


def test_platforms_accept_content_objects():
    platforms = Platforms(**_object_platforms("текст"))
    assert platforms.telegram.content == "текст"
    assert platforms.vk.content == "текст"


def test_post_document_accepts_plain_strings():
    """Регрессия job 12: модель записала площадки строками вместо {"content": ...}."""
    document = PostDocument(
        source=SOURCE,
        image_prompt="a" * 40,
        platforms=_plain_platforms("текст площадки"),
    )
    assert document.platforms.vk.content == "текст площадки"


def test_post_document_accepts_content_objects():
    document = PostDocument(
        source=SOURCE,
        image_prompt="a" * 40,
        platforms=_object_platforms("текст"),
    )
    assert document.platforms.x.content == "текст"


def test_post_document_partial_accepts_plain_strings():
    document = PostDocumentPartial(
        source=SOURCE,
        platforms={"telegram": "текст", "x": {"content": "english text"}},
    )
    assert document.platforms.telegram is not None
    assert document.platforms.telegram.content == "текст"
    assert document.platforms.x is not None
    assert document.platforms.x.content == "english text"
    assert document.platforms.vk is None


def test_post_document_rejects_missing_platform():
    with pytest.raises(ValidationError):
        PostDocument(source=SOURCE, image_prompt="a" * 40, platforms={"telegram": "текст"})


def test_platforms_partial_rejects_non_text_value():
    with pytest.raises(ValidationError):
        PlatformsPartial(telegram=42)
