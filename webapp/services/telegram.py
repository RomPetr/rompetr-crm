from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

from webapp.config import get_settings

log = logging.getLogger(__name__)
CAPTION_LIMIT = 1024
MESSAGE_LIMIT = 4096


@dataclass
class PublishResult:
    ok: bool
    external_id: str | None = None
    url: str | None = None
    error: str | None = None
    unknown: bool = False


def _multipart(fields: dict, files: dict) -> tuple[bytes, str]:
    boundary = "----crm" + uuid.uuid4().hex
    body = bytearray()
    for name, value in fields.items():
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        body += str(value).encode() + b"\r\n"
    for name, (filename, data, ctype) in files.items():
        body += f"--{boundary}\r\n".encode()
        body += (
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
        ).encode()
        body += f"Content-Type: {ctype}\r\n\r\n".encode()
        body += data + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def _api(token: str, method: str, fields: dict | None = None, files: dict | None = None) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    if files:
        body, ctype = _multipart(fields or {}, files)
    else:
        body = urllib.parse.urlencode(fields or {}).encode()
        ctype = "application/x-www-form-urlencoded"
    request = urllib.request.Request(url, data=body, headers={"Content-Type": ctype})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "description": f"HTTP {exc.code}"}


def split_text(text: str, limit: int) -> list[str]:
    parts: list[str] = []
    current = ""
    for block in text.split("\n\n"):
        candidate = block if not current else current + "\n\n" + block
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                parts.append(current)
            while len(block) > limit:
                parts.append(block[:limit])
                block = block[limit:]
            current = block
    if current:
        parts.append(current)
    return parts or [text[:limit]]


def publish(text: str, image_path: Path | None) -> PublishResult:
    settings = get_settings()
    token = settings.telegram_bot_token.get_secret_value()
    chat = settings.telegram_chat_id
    if not token or not chat:
        return PublishResult(ok=False, error="TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID не заданы")

    last_error = "unknown"
    for attempt in (1, 2):
        try:
            me = _api(token, "getMe")
            if not me.get("ok"):
                return PublishResult(ok=False, error=f"getMe: {me.get('description')}")
            if image_path and image_path.exists():
                fields = {"chat_id": chat}
                if len(text) <= CAPTION_LIMIT:
                    fields["caption"] = text
                files = {"photo": (image_path.name, image_path.read_bytes(), "image/png")}
                result = _api(token, "sendPhoto", fields, files)
                if not result.get("ok"):
                    return PublishResult(ok=False, error=f"sendPhoto: {result.get('description')}")
                message_id = result["result"]["message_id"]
                if len(text) > CAPTION_LIMIT:
                    for part in split_text(text, MESSAGE_LIMIT):
                        extra = _api(token, "sendMessage", {"chat_id": chat, "text": part})
                        if not extra.get("ok"):
                            return PublishResult(
                                ok=False, error=f"sendMessage: {extra.get('description')}"
                            )
            else:
                message_id = None
                for part in split_text(text, MESSAGE_LIMIT):
                    result = _api(token, "sendMessage", {"chat_id": chat, "text": part})
                    if not result.get("ok"):
                        return PublishResult(ok=False, error=f"sendMessage: {result.get('description')}")
                    message_id = result["result"]["message_id"]
            username = chat.lstrip("@") if chat.startswith("@") else None
            url = f"https://t.me/{username}/{message_id}" if username and message_id else None
            return PublishResult(ok=True, external_id=str(message_id), url=url)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = str(exc)
            log.warning("telegram publish attempt %s failed: %s", attempt, exc)
            if attempt == 1:
                time.sleep(2)
                continue
            return PublishResult(ok=False, error=last_error, unknown=True)
    return PublishResult(ok=False, error=last_error)
