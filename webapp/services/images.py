from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request

from sqlalchemy.orm import Session

from webapp.config import get_settings
from webapp.models.content import Asset, Post
from webapp.services import media


def _request(url: str, payload: dict, key: str) -> bytes:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        data = json.loads(response.read())
    item = data.get("data", [{}])[0]
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"])
    if item.get("url"):
        with urllib.request.urlopen(item["url"], timeout=120) as response:
            return response.read()
    raise RuntimeError("API изображений не вернул данные")


def generate(db: Session, post: Post, user_id: int | None) -> Asset:
    settings = get_settings()
    key = settings.proxyapi_key.get_secret_value()
    if not key:
        raise RuntimeError("PROXYAPI_KEY не задан")
    prompt = (post.image_prompt or "").strip()
    if len(prompt) < 20:
        raise RuntimeError("image_prompt пустой или слишком короткий")

    base = settings.proxyapi_base_url.rstrip("/")
    attempts = (
        (
            f"{base}/v1/images/generations",
            {
                "model": settings.image_model,
                "prompt": prompt,
                "size": "1024x1024",
                "output_format": "png",
            },
        ),
        (
            f"{base}/openai/v1/images/generations",
            {
                "model": settings.image_fallback_model,
                "prompt": prompt,
                "size": "1024x1024",
                "quality": "medium",
                "output_format": "png",
            },
        ),
    )

    last_error = "unknown"
    for url, payload in attempts:
        try:
            raw = _request(url, payload, key)
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code}: " + exc.read().decode("utf-8", "replace")[:400]
            continue
        except Exception as exc:  # network
            last_error = str(exc)
            continue
        if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
            last_error = "ответ не является PNG"
            continue
        return media.save_bytes(db, post, raw, user_id)

    raise RuntimeError(last_error)
