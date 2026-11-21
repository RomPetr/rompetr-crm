#!/usr/bin/env python3
"""Проверка и публикация готового JSON-поста из старой схемы.

Примеры:
    python -I scripts/smoke_publish.py posts/161126/<base>/<base>.json --dry-run
    python -I scripts/smoke_publish.py posts/161126/<base>/<base>.json --platforms telegram
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from webapp.config import get_settings  # noqa: E402
from webapp.schemas.post_document import PostDocument  # noqa: E402
from webapp.services import telegram, vk  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-публикация поста")
    parser.add_argument("json", help="путь к JSON поста")
    parser.add_argument("--dry-run", action="store_true", help="только проверка, без отправки")
    parser.add_argument(
        "--platforms",
        default="telegram,vk",
        help="через запятую: telegram,vk (по умолчанию оба)",
    )
    args = parser.parse_args()

    path = Path(args.json).resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    document = PostDocument.model_validate(data)
    settings = get_settings()

    image = path.parent / f"{path.stem}-image-1.png"
    targets = [name.strip() for name in args.platforms.split(",") if name.strip()]

    print(f"JSON: {path}")
    print(f"Источник: {document.source.publisher} · {document.source.published_at}")
    print(f"Изображение: {image if image.exists() else 'нет'}")
    print(f"Telegram: {'настроен' if settings.telegram_bot_token.get_secret_value() else 'нет ключа'}")
    print(f"VK: {'настроен' if settings.vk_access_token.get_secret_value() else 'нет ключа'}")

    if args.dry_run:
        for name in targets:
            if name == "telegram":
                print(f"telegram: {len(document.platforms.telegram.content)} символов")
            elif name == "vk":
                print(f"vk: {len(document.platforms.vk.content)} символов")
        print("DRY-RUN: отправка не выполнялась")
        return 0

    failures = 0
    for name in targets:
        if name == "telegram":
            result = telegram.publish(
                document.platforms.telegram.content, image if image.exists() else None
            )
        elif name == "vk":
            result = vk.publish(
                document.platforms.vk.content, image if image.exists() else None
            )
        else:
            print(f"ERROR: неизвестная площадка {name}", file=sys.stderr)
            failures += 1
            continue
        if result.ok:
            print(f"OK {name}: {result.url or result.external_id}")
        else:
            print(f"FAIL {name}: {result.error}")
            failures += 1
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
