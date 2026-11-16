from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from webapp.config import get_settings

log = logging.getLogger(__name__)


@dataclass
class PublishResult:
    ok: bool
    external_id: str | None = None
    url: str | None = None
    error: str | None = None
    unknown: bool = False


def publish(text: str) -> PublishResult:
    settings = get_settings()
    token = settings.vk_access_token.get_secret_value()
    group = settings.vk_group_id
    if not token or not group:
        return PublishResult(ok=False, error="VK_ACCESS_TOKEN/VK_GROUP_ID не заданы")
    owner_id = "-" + re.sub(r"\D", "", group)
    payload = urllib.parse.urlencode(
        {
            "owner_id": owner_id,
            "from_group": 1,
            "message": text,
            "access_token": token,
            "v": "5.199",
        }
    ).encode()

    last_error = "unknown"
    for attempt in (1, 2):
        try:
            request = urllib.request.Request(
                "https://api.vk.com/method/wall.post",
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = str(exc)
            log.warning("vk publish attempt %s failed: %s", attempt, exc)
            if attempt == 1:
                time.sleep(2)
                continue
            return PublishResult(ok=False, error=last_error, unknown=True)

        if "response" in result:
            post_id = result["response"].get("post_id")
            return PublishResult(
                ok=True,
                external_id=str(post_id),
                url=f"https://vk.com/wall{owner_id}_{post_id}",
            )

        error = result.get("error", {})
        code = error.get("error_code")
        message = error.get("error_msg", "unknown VK error")
        if code == 27:
            return PublishResult(ok=False, error="VK error 27: токен не поддерживает этот метод")
        return PublishResult(ok=False, error=f"VK {code}: {message}")

    return PublishResult(ok=False, error=last_error)
