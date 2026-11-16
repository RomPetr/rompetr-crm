from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request

from sqlalchemy.orm import Session

from webapp.config import get_settings
from webapp.models.content import Asset, Post
from webapp.services import media

IMAGE_MODELS = ("black-forest-labs/flux.2-pro", "gpt-image-1-mini")


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


def _attempt(model: str) -> tuple[str, dict]:
    settings = get_settings()
    base = settings.proxyapi_base_url.rstrip("/")
    if model == "gpt-image-1-mini":
        return (
            f"{base}/openai/v1/images/generations",
            {
                "model": "gpt-image-1-mini",
                "prompt": "",
                "size": "1024x1024",
                "quality": "medium",
                "output_format": "png",
            },
        )
    return (
        f"{base}/v1/images/generations",
        {
            "model": "black-forest-labs/flux.2-pro",
            "prompt": "",
            "size": "1024x1024",
            "output_format": "png",
        },
    )


def generate(db: Session, post: Post, user_id: int | None, model: str | None = None) -> Asset:
    settings = get_settings()
    key = settings.proxyapi_key.get_secret_value()
    if not key:
        raise RuntimeError("PROXYAPI_KEY не задан")
    prompt = (post.image_prompt or "").strip()
    if len(prompt) < 20:
        raise RuntimeError("image_prompt пустой или слишком короткий")

    chosen = model if model in IMAGE_MODELS else settings.image_model
    if chosen not in IMAGE_MODELS:
        chosen = IMAGE_MODELS[0]
    order = [chosen] + [name for name in IMAGE_MODELS if name != chosen]

    last_error = "unknown"
    for name in order:
        url, payload = _attempt(name)
        payload["prompt"] = prompt
        try:
            raw = _request(url, payload, key)
        except urllib.error.HTTPError as exc:
            last_error = f"{name}: HTTP {exc.code}: " + exc.read().decode("utf-8", "replace")[:300]
            continue
        except Exception as exc:  # network
            last_error = f"{name}: {exc}"
            continue
        if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
            last_error = f"{name}: ответ не является PNG"
            continue
        return media.save_bytes(db, post, raw, user_id)

    raise RuntimeError(last_error)
