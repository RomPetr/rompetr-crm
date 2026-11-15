#!/usr/bin/env python3
"""Переносит секреты из legacy .claude/env.txt в .env.

Формат источника: строки `KEY: value`, разделители `---` игнорируются.
Значения никогда не печатаются. Существующий .env не перезаписывается без --force.
"""

from __future__ import annotations

import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEGACY = ROOT / ".claude" / "env.txt"
EXAMPLE = ROOT / ".env.example"
TARGET = ROOT / ".env"

KEY_MAP = {
    "ACCESS_TOKEN": "TELEGRAM_BOT_TOKEN",
    "TG_GROUP_ID": "TELEGRAM_CHAT_ID",
    "TG_BOT": "TELEGRAM_BOT_USERNAME",
    "PROXY_API_KEY": "PROXYAPI_KEY",
    "PROXY_API_KEY2": "PROXYAPI_KEY_SECONDARY",
    "VK_ACCESS_TOKEN": "VK_ACCESS_TOKEN",
    "VK_GROUP_ID": "VK_GROUP_ID",
}

EXTRACTORS = {
    "TELEGRAM_BOT_TOKEN": re.compile(r"\d{8,10}:[A-Za-z0-9_-]{35}"),
    "PROXYAPI_KEY": re.compile(r"sk-[A-Za-z0-9]+"),
    "PROXYAPI_KEY_SECONDARY": re.compile(r"sk-[A-Za-z0-9]+"),
    "VK_ACCESS_TOKEN": re.compile(r"vk1\.[A-Za-z0-9._-]+"),
}


def parse_legacy(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("---") or line.startswith("#"):
            continue
        match = re.match(r"^([A-Z0-9_]+)\s*:\s*(.+)$", line)
        if match:
            values[match.group(1)] = match.group(2).strip()
    return values


def parse_example(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def extract(name: str, raw: str) -> str:
    pattern = EXTRACTORS.get(name)
    if pattern:
        match = pattern.search(raw)
        if match:
            return match.group(0)
    return raw


def main(argv: list[str]) -> int:
    dry_run = "--dry-run" in argv
    force = "--force" in argv

    if TARGET.exists() and not force and not dry_run:
        print("ERROR: .env уже существует. Используйте --force для перезаписи.", file=sys.stderr)
        return 1

    legacy = parse_legacy(LEGACY)
    values = parse_example(EXAMPLE)
    if not values:
        print("ERROR: .env.example не найден или пуст.", file=sys.stderr)
        return 1

    values["APP_SECRET_KEY"] = secrets.token_urlsafe(48)
    if not values.get("ADMIN_EMAIL"):
        values["ADMIN_EMAIL"] = "admin@rompetr.ru"

    mapped: list[str] = []
    for source, target in KEY_MAP.items():
        raw = legacy.get(source)
        if not raw:
            continue
        values[target] = extract(target, raw)
        mapped.append(target)

    lines = [
        "# Сгенерировано scripts/migrate_env.py. Не коммитить.",
        "# Значения секретов не печатались и не логировались.",
    ]
    for key, value in values.items():
        lines.append(f"{key}={value}")
    content = "\n".join(lines) + "\n"

    if dry_run:
        print(f"DRY-RUN: будет записано {len(values)} переменных")
        print("Переменные из legacy:", ", ".join(mapped) if mapped else "нет")
        return 0

    TARGET.write_text(content, encoding="utf-8")
    if hasattr(TARGET, "chmod"):
        try:
            TARGET.chmod(0o600)
        except OSError:
            pass
    print(f"OK: .env создан, переменных: {len(values)}")
    print("Из legacy перенесены:", ", ".join(mapped) if mapped else "нет")
    print("Дальше: ротировать VK, Telegram и ProxyAPI ключи до первого push.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
