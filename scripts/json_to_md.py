#!/usr/bin/env python3
"""Создаёт MD-копию поста рядом с JSON для ручного копирования.

Тексты берутся из platforms.*.content как есть: реальные переносы строк,
без экранированных \\n и без служебных обёрток JSON.

Пример:
    python -I scripts/json_to_md.py posts/161126/<base>/<base>.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POSTS_ROOT = (ROOT / "posts").resolve()
ORDER = ("telegram", "vk", "instagram", "x", "tiktok")
TITLES = {
    "telegram": "Telegram",
    "vk": "ВКонтакте",
    "instagram": "Instagram",
    "x": "X (English)",
    "tiktok": "TikTok",
}


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: json_to_md.py <post.json>", file=sys.stderr)
        return 2

    json_path = Path(argv[0]).resolve()
    if POSTS_ROOT not in json_path.parents:
        print("ERROR: JSON должен лежать внутри posts/", file=sys.stderr)
        return 2
    if not json_path.exists():
        print(f"ERROR: файл не найден: {json_path}", file=sys.stderr)
        return 2

    data = json.loads(json_path.read_text(encoding="utf-8"))
    source = data.get("source", {})
    platforms = data.get("platforms", {})

    image = json_path.parent / f"{json_path.stem}-image-1.png"
    lines: list[str] = []
    lines.append(f"# {source.get('title', 'Пост')}")
    lines.append("")
    if source.get("publisher"):
        lines.append(f"**Источник:** {source['publisher']} — {source.get('url', '')}")
    if source.get("published_at"):
        lines.append(f"**Дата:** {source['published_at']}")
    lines.append(f"**JSON:** `{json_path.name}`")
    if image.exists():
        lines.append(f"**Изображение:** `{image.name}`")
    lines.append("")
    lines.append("---")

    for name in ORDER:
        content = (platforms.get(name) or {}).get("content", "").strip()
        if not content:
            continue
        lines.append("")
        lines.append(f"## {TITLES.get(name, name)}")
        lines.append("")
        lines.append(content)
        lines.append("")
        lines.append("---")

    lines.append("")
    lines.append("Скопируйте текст под нужным заголовком — переносы строк уже настоящие.")
    out_path = json_path.with_suffix(".md")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"OK: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
