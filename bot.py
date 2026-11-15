#!/usr/bin/env python3
"""Автопостинг новости Content Plant в Telegram-канал @defidexmind.

Берёт platforms.telegram.content из JSON поста и первую PNG, созданную Pixly
(<base>-image-*.png), и публикует их через Telegram Bot API.

Примеры:
    python -I bot.py posts/131126/2026-11-13-220929-crypto-ai-social-content/2026-11-13-220929-crypto-ai-social-content.json
    python -I bot.py posts/131126 --image 2
    python -I bot.py --latest
    python -I bot.py --latest --dry-run
"""

import argparse
import glob
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".claude" / "env.txt"
POSTS_DIR = ROOT / "posts"
CAPTION_LIMIT = 1024
MESSAGE_LIMIT = 4096


def read_env():
    values = {}
    if not ENV_FILE.exists():
        return values
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Z0-9_]+)\s*:\s*(.+)$", line.strip())
        if m:
            values[m.group(1)] = m.group(2).strip()
    return values


def find_latest_json(start: Path):
    candidates = [
        p
        for p in start.rglob("*crypto-ai-social-content.json")
        if p.is_file() and "avatars" not in p.parts
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def resolve_json(arg: str):
    p = Path(arg)
    if p.is_dir():
        return find_latest_json(p)
    if p.is_file():
        return p
    return None


def find_images(json_path: Path):
    base = json_path.stem
    files = sorted(
        Path(p)
        for p in glob.glob(str(json_path.parent / f"{base}-image-*.png"))
        if os.path.getsize(p) > 0
    )
    return files


def multipart_body(fields, files):
    boundary = "----cp" + uuid.uuid4().hex
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


def api(token, method, fields=None, files=None):
    url = f"https://api.telegram.org/bot{token}/{method}"
    if files:
        body, ctype = multipart_body(fields or {}, files)
    else:
        body = urllib.parse.urlencode(fields or {}).encode()
        ctype = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, headers={"Content-Type": ctype})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "description": f"HTTP {exc.code}"}


def split_text(text, limit):
    parts, current = [], ""
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


def main():
    parser = argparse.ArgumentParser(description="Публикация новости Content Plant в Telegram")
    parser.add_argument("path", nargs="?", help="JSON поста или папка; без аргумента — --latest")
    parser.add_argument("--latest", action="store_true", help="взять самый свежий JSON из posts/")
    parser.add_argument("--chat", help="chat_id или @username (по умолчанию TG_GROUP_ID)")
    parser.add_argument("--image", type=int, default=1, help="номер PNG (1..N), 0 — без картинки")
    parser.add_argument("--text-only", action="store_true", help="не прикреплять картинку")
    parser.add_argument("--dry-run", action="store_true", help="показать план без отправки")
    args = parser.parse_args()

    env = read_env()
    token = env.get("ACCESS_TOKEN") or env.get("TELEGRAM_BOT_TOKEN")
    chat = args.chat or env.get("TG_GROUP_ID")
    if not token:
        sys.exit("ERROR: ACCESS_TOKEN не найден в .claude/env.txt")
    if not chat:
        sys.exit("ERROR: TG_GROUP_ID не найден в .claude/env.txt")

    if args.latest or not args.path:
        json_path = find_latest_json(POSTS_DIR)
    else:
        json_path = resolve_json(args.path)
    if not json_path or not json_path.exists():
        sys.exit(f"ERROR: JSON не найден: {args.path}")

    data = json.loads(json_path.read_text(encoding="utf-8"))
    text = data["platforms"]["telegram"]["content"].strip()
    images = [] if args.text_only else find_images(json_path)
    image = None
    if images:
        idx = max(1, args.image) - 1
        if idx >= len(images):
            sys.exit(f"ERROR: запрошена картинка {args.image}, найдено {len(images)}")
        image = images[idx]

    print(f"JSON: {json_path}")
    print(f"CHAT: {chat}")
    print(f"TEXT: {len(text)} символов")
    print(f"IMAGE: {image if image else 'нет'}")

    if args.dry_run:
        print("DRY-RUN: отправка не выполнялась")
        return

    me = api(token, "getMe")
    if not me.get("ok"):
        sys.exit(f"ERROR getMe: {me.get('description')}")
    chat_info = api(token, "getChat", {"chat_id": chat})
    if not chat_info.get("ok"):
        sys.exit(f"ERROR getChat: {chat_info.get('description')}")

    if image:
        fields = {"chat_id": chat}
        if len(text) <= CAPTION_LIMIT:
            fields["caption"] = text
        files = {"photo": (image.name, image.read_bytes(), "image/png")}
        result = api(token, "sendPhoto", fields, files)
        if result.get("ok"):
            msg_id = result["result"]["message_id"]
            print(f"OK photo message_id={msg_id}")
            if len(text) > CAPTION_LIMIT:
                for part in split_text(text, MESSAGE_LIMIT):
                    extra = api(token, "sendMessage", {"chat_id": chat, "text": part})
                    if not extra.get("ok"):
                        sys.exit(f"ERROR sendMessage: {extra.get('description')}")
                    print(f"OK text message_id={extra['result']['message_id']}")
        else:
            sys.exit(f"ERROR sendPhoto: {result.get('description')}")
        msg_id = result["result"]["message_id"]
    else:
        msg_id = None
        for part in split_text(text, MESSAGE_LIMIT):
            result = api(token, "sendMessage", {"chat_id": chat, "text": part})
            if not result.get("ok"):
                sys.exit(f"ERROR sendMessage: {result.get('description')}")
            msg_id = result["result"]["message_id"]
            print(f"OK text message_id={msg_id}")

    username = (chat_info["result"].get("username") or "").lstrip("@")
    if msg_id and username:
        print(f"LINK: https://t.me/{username}/{msg_id}")


if __name__ == "__main__":
    main()
