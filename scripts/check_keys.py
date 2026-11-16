#!/usr/bin/env python3
"""Проверяет, что ключи из .env рабочие, и ищет старые копии секретов.

Никогда не печатает значения ключей — только статусы и имена переменных.
"""

from __future__ import annotations

import hashlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
LEGACY = ROOT / ".claude" / "env.txt"
SKILL_FILES = list((ROOT / ".claude" / "skills").rglob("*.txt"))

PATTERNS = {
    "telegram": re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),
    "vk": re.compile(r"vk1\.[A-Za-z0-9._-]{20,}"),
    "proxyapi": re.compile(r"sk-[A-Za-z0-9]{20,}"),
}


def read_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV.exists():
        return values
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def http(url: str, *, token: str | None = None, timeout: int = 20) -> tuple[int, str]:
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(4000).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(2000).decode("utf-8", "replace")
    except Exception as exc:  # network
        return 0, str(exc)


def mask(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def check_telegram(token: str) -> bool:
    status, body = http(f"https://api.telegram.org/bot{token}/getMe")
    ok = status == 200 and '"ok":true' in body
    print(f"telegram: {'OK' if ok else 'FAIL'} (http {status})")
    return ok


def check_vk(token: str, group_id: str) -> bool:
    query = urllib.parse.urlencode(
        {"group_id": re.sub(r"\D", "", group_id), "access_token": token, "v": "5.199"}
    )
    status, body = http(f"https://api.vk.com/method/groups.getById?{query}")
    ok = status == 200 and '"response"' in body
    print(f"vk: {'OK' if ok else 'FAIL'} (http {status})")
    return ok


def check_proxyapi(token: str) -> bool:
    status, body = http("https://api.proxyapi.ru/v1/models", token=token)
    ok = status == 200
    print(f"proxyapi: {'OK' if ok else 'FAIL'} (http {status})")
    return ok


def find_legacy_copies(secrets: dict[str, str]) -> int:
    copies = 0
    for path in [LEGACY, *SKILL_FILES]:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for family, pattern in PATTERNS.items():
            for match in pattern.findall(text):
                digest = mask(match)
                for name, value in secrets.items():
                    if digest == mask(value):
                        print(f"legacy copy: {path.relative_to(ROOT)} содержит тот же {family} ключ, что {name}")
                        copies += 1
    return copies


def main() -> int:
    values = read_env()
    if not values:
        print("ERROR: .env не найден", file=sys.stderr)
        return 1

    telegram = values.get("TELEGRAM_BOT_TOKEN", "")
    vk = values.get("VK_ACCESS_TOKEN", "")
    proxy = values.get("PROXYAPI_KEY", "")

    if not any([telegram, vk, proxy]):
        print("ERROR: в .env нет ни одного ключа", file=sys.stderr)
        return 1

    results = []
    secrets = {}
    if telegram:
        secrets["TELEGRAM_BOT_TOKEN"] = telegram
        results.append(check_telegram(telegram))
    if vk:
        secrets["VK_ACCESS_TOKEN"] = vk
        results.append(check_vk(vk, values.get("VK_GROUP_ID", "")))
    if proxy:
        secrets["PROXYAPI_KEY"] = proxy
        results.append(check_proxyapi(proxy))

    copies = find_legacy_copies(secrets)
    if copies:
        print("ВНИМАНИЕ: старые копии ещё лежат в .claude/skills. Удалите их после ротации.")
    else:
        print("legacy copies: не найдено")

    print("")
    print("Проверка показывает только работоспособность ключей.")
    print("Отзыв старых ключей виден лишь в кабинетах VK, BotFather и ProxyAPI.")
    return 0 if all(results) else 2


if __name__ == "__main__":
    sys.exit(main())
