from __future__ import annotations

import re
from datetime import date

from pydantic import BaseModel, HttpUrl, field_validator, model_validator

PUBLISHERS = {"The Block", "The Defiant", "Blockworks", "CoinDesk", "Decrypt"}
PUBLISHER_HOMEPAGES = {
    "The Block": "https://www.theblock.co/",
    "The Defiant": "https://thedefiant.io/",
    "Blockworks": "https://blockworks.co/",
    "CoinDesk": "https://www.coindesk.com/",
    "Decrypt": "https://decrypt.co/",
}
SCHEMA_VERSION = "crypto-ai-social-content/v1"

SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"vk1\.[A-Za-z0-9._-]{20,}"),
    re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)
PROFIT_PATTERNS = (
    re.compile(r"\b100\s*x\b", re.I),
    re.compile(r"гарантированн\w*\s+прибыл", re.I),
    re.compile(r"безрисков\w*", re.I),
)


class Source(BaseModel):
    title: str
    url: HttpUrl
    published_at: date
    publisher: str

    @field_validator("publisher")
    @classmethod
    def known_publisher(cls, value: str) -> str:
        if value not in PUBLISHERS:
            raise ValueError(f"Источник должен быть одним из: {', '.join(sorted(PUBLISHERS))}")
        return value

    @field_validator("title")
    @classmethod
    def title_len(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > 500:
            raise ValueError("Заголовок источника: от 1 до 500 символов")
        return value


class PlatformText(BaseModel):
    content: str

    @model_validator(mode="before")
    @classmethod
    def accept_plain_text(cls, data: object) -> object:
        """Принять и строку, и {"content": ...}: модели иногда пишут площадку строкой."""
        if isinstance(data, str):
            return {"content": data}
        return data


class Platforms(BaseModel):
    telegram: PlatformText
    instagram: PlatformText
    x: PlatformText
    tiktok: PlatformText
    vk: PlatformText


class PostDocument(BaseModel):
    schema_version: str = SCHEMA_VERSION
    source: Source
    image_prompt: str
    platforms: Platforms

    @field_validator("schema_version")
    @classmethod
    def version(cls, value: str) -> str:
        if value != SCHEMA_VERSION:
            raise ValueError(f"schema_version должен быть {SCHEMA_VERSION}")
        return value

    @field_validator("image_prompt")
    @classmethod
    def prompt_len(cls, value: str) -> str:
        value = value.strip()
        if not 20 <= len(value) <= 2000:
            raise ValueError("image_prompt: от 20 до 2000 символов")
        return value


def hashtags(text: str) -> list[str]:
    return re.findall(r"#\w+", text)


def word_count(text: str) -> int:
    return len(text.split())


def _common_checks(text: str, platform: str) -> list[str]:
    errors: list[str] = []
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            errors.append(f"{platform}: похоже на секрет или ключ")
            break
    for pattern in PROFIT_PATTERNS:
        if pattern.search(text):
            errors.append(f"{platform}: обещание доходности или «безрисковости»")
            break
    return errors


def validate_platforms(platforms: dict[str, str], publisher: str | None = None) -> list[str]:
    """Проверяет только переданные (включённые) площадки."""
    errors: list[str] = []

    if publisher:
        homepage = PUBLISHER_HOMEPAGES.get(publisher)
        if homepage:
            for name, text in platforms.items():
                if homepage not in text:
                    errors.append(f"{name}: добавьте ссылку на главную источника {homepage}")

    if "telegram" in platforms:
        text = platforms["telegram"]
        if not 800 <= len(text) <= 1024:
            errors.append(f"telegram: {len(text)} символов, нужно 800–1024")
        if hashtags(text):
            errors.append("telegram: уберите хэштеги — они не используются")
        errors += _common_checks(text, "telegram")

    if "vk" in platforms:
        text = platforms["vk"]
        if not 700 <= len(text) <= 1500:
            errors.append(f"vk: {len(text)} символов, нужно 700–1500")
        errors += _common_checks(text, "vk")

    if "instagram" in platforms:
        text = platforms["instagram"]
        if not 100 <= word_count(text) <= 200:
            errors.append(f"instagram: {word_count(text)} слов, нужно 100–200")
        if not 5 <= len(hashtags(text)) <= 10:
            errors.append("instagram: нужно 5–10 хэштегов")
        errors += _common_checks(text, "instagram")

    if "tiktok" in platforms:
        text = platforms["tiktok"]
        if not 50 <= word_count(text) <= 120:
            errors.append(f"tiktok: {word_count(text)} слов, нужно 50–120")
        if not 3 <= len(hashtags(text)) <= 5:
            errors.append("tiktok: нужно 3–5 хэштегов")
        errors += _common_checks(text, "tiktok")

    if "x" in platforms:
        text = platforms["x"]
        if len(text) > 280:
            errors.append(f"x: {len(text)} символов, максимум 280")
        if re.search(r"[А-Яа-яЁё]", text):
            errors.append("x: только английский язык")
        errors += _common_checks(text, "x")

    return errors


def validate_document(
    source: dict, image_prompt: str, platforms: dict[str, str], *, check_prompt: bool = True
) -> list[str]:
    from pydantic import ValidationError

    errors = validate_platforms(platforms, source.get("publisher"))
    try:
        Source(**source)
    except ValidationError as exc:
        for item in exc.errors():
            field = ".".join(str(part) for part in item["loc"])
            errors.append(f"source.{field}: {item['msg']}")
    prompt = image_prompt.strip()
    if check_prompt and not 20 <= len(prompt) <= 2000:
        errors.append("image_prompt: от 20 до 2000 символов")
    return errors


class PlatformsPartial(BaseModel):
    telegram: PlatformText | None = None
    instagram: PlatformText | None = None
    x: PlatformText | None = None
    tiktok: PlatformText | None = None
    vk: PlatformText | None = None


class PostDocumentPartial(BaseModel):
    schema_version: str = SCHEMA_VERSION
    source: Source
    image_prompt: str = ""
    platforms: PlatformsPartial
