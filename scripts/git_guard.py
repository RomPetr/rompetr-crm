#!/usr/bin/env python3
"""Политика git для rompetr-crm.

Разрешает коммитить только системные файлы. Блокирует данные, медиа, секреты,
сторонние каталоги, большие и бинарные файлы. Используется агентом gitpublisher,
pre-commit и pre-push хуками.

Коды выхода:
  0 — чисто
  2 — запрещённый путь
  3 — найден секрет
  4 — превышен размер или бинарный файл
  5 — ошибка git
  6 — ошибка политики/конфигурации
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

MAX_FILE_BYTES = 10 * 1024 * 1024
TEXT_SCAN_LIMIT = 1024 * 1024
DIFF_SCAN_LIMIT = 16 * 1024 * 1024

ALLOW_PREFIXES = (
    "webapp/",
    "scripts/",
    "tests/",
    "alembic/",
    "docs/",
    ".claude/agents/",
    ".claude/commands/",
    ".claude/plans/",
    ".claude/skills/",
    ".github/",
    ".githooks/",
)

ALLOW_FILES = {
    ".gitignore",
    ".gitattributes",
    ".env.example",
    "README.md",
    "LICENSE",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "alembic.ini",
    "bot.py",
    "PIPELINE.md",
    "PUBLISH-COMMAND.md",
    "PUBLICATIONS.md",
    ".claude/pixly-coin-icons.json",
}

DENY_PREFIXES = (
    "posts/",
    "var/",
    "media/",
    "backups/",
    ".chrome-x-profile/",
    ".mcp-servers/",
    "node_modules/",
    "__pycache__/",
    ".venv/",
    "venv/",
    ".git/",
)

DENY_FILES = {
    ".env",
    ".claude/env.txt",
    ".claude/settings.local.json",
    ".claude/scheduled_tasks.json",
}

ALLOW_IMAGE_PREFIXES = ("docs/images/", "webapp/static/img/trust/")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif")

DENY_SUFFIXES = (
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".ico",
    ".pdf",
    ".zip",
    ".sqlite3",
    ".db",
    ".log",
    ".pyc",
    ".pyo",
    ".pem",
    ".key",
)

SECRET_SKILL_FILES = {
    "env.txt",
    "api_vk.txt",
    "id_vk.txt",
    "auto_posting_image_api.txt",
}

SECRET_PATTERNS = (
    ("proxyapi/anthropic key", re.compile(r"sk-(?:ant-[a-z0-9]+-)?[A-Za-z0-9_-]{20,}")),
    ("vk token", re.compile(r"vk1\.[A-Za-z0-9._-]{20,}")),
    ("telegram bot token", re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b")),
    ("github token", re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}")),
    ("aws key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("slack token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
)

EXIT_CLEAN = 0
EXIT_DENY_PATH = 2
EXIT_SECRET = 3
EXIT_SIZE = 4
EXIT_GIT = 5
EXIT_POLICY = 6


def run_git(repo: Path, *args: str) -> bytes:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(repo),
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise RuntimeError(f"git не запускается: {exc}") from exc
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace").strip())
    return proc.stdout


def repo_root() -> Path:
    out = run_git(Path.cwd(), "rev-parse", "--show-toplevel")
    return Path(out.decode("utf-8", "replace").strip())


def normalize(path: str) -> str:
    path = path.replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


def classify(path: str) -> tuple[bool, str]:
    p = normalize(path)
    lower = p.lower()
    if not p:
        return False, "пустой путь"
    if lower.startswith(".claude/skills/") and p.rsplit("/", 1)[-1].lower() in SECRET_SKILL_FILES:
        return False, "секрет скилла"
    if p in DENY_FILES or lower in DENY_FILES:
        return False, "запрещённый файл"
    for prefix in DENY_PREFIXES:
        if lower.startswith(prefix):
            return False, f"запрещённый каталог {prefix}"
    if lower.startswith(ALLOW_IMAGE_PREFIXES) and lower.endswith(IMAGE_SUFFIXES):
        return True, "изображение документации или статики"
    if lower.endswith(DENY_SUFFIXES):
        return False, "бинарный или служебный файл"
    if lower.startswith(".env") and lower != ".env.example":
        return False, "файл окружения"
    if p in ALLOW_FILES:
        return True, "разрешённый файл"
    for prefix in ALLOW_PREFIXES:
        if lower.startswith(prefix):
            return True, f"разрешённый каталог {prefix}"
    return False, "путь вне allowlist"


def scan_text(text: str, label: str) -> list[tuple[int, str]]:
    findings: list[tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for name, pattern in SECRET_PATTERNS:
            if pattern.search(line):
                findings.append((EXIT_SECRET, f"{label}:{lineno}: похоже на {name}"))
    return findings


def is_probably_text(raw: bytes) -> bool:
    sample = raw[:8192]
    return b"\x00" not in sample


def staged_paths(repo: Path) -> list[str]:
    out = run_git(repo, "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
    return [normalize(p) for p in out.decode("utf-8", "surrogateescape").split("\0") if p]


def tracked_paths(repo: Path) -> list[str]:
    out = run_git(repo, "ls-files", "-z")
    return [normalize(p) for p in out.decode("utf-8", "surrogateescape").split("\0") if p]


def staged_size(repo: Path, path: str) -> int:
    out = run_git(repo, "cat-file", "-s", f":{path}")
    return int(out.decode("ascii").strip())


def check_paths(repo: Path, paths: list[str], sizes: dict[str, int]) -> list[tuple[int, str]]:
    violations: list[tuple[int, str]] = []
    for path in paths:
        allowed, reason = classify(path)
        if not allowed:
            violations.append((EXIT_DENY_PATH, f"{path}: {reason}"))
            continue
        size = sizes.get(path)
        if size is None:
            try:
                size = os.path.getsize(repo / path)
            except OSError:
                size = 0
        if size > MAX_FILE_BYTES:
            violations.append((EXIT_SIZE, f"{path}: {size} байт больше лимита"))
    return violations


def check_staged_secrets(repo: Path) -> list[tuple[int, str]]:
    diff = run_git(repo, "diff", "--cached", "--unified=0", "--no-color")
    if len(diff) > DIFF_SCAN_LIMIT:
        return [(EXIT_POLICY, "staged diff слишком большой для проверки")]
    return scan_text(diff.decode("utf-8", "replace"), "staged diff")


def check_tracked_secrets(repo: Path, paths: list[str]) -> list[tuple[int, str]]:
    findings: list[tuple[int, str]] = []
    for path in paths:
        full = repo / path
        try:
            if full.stat().st_size > TEXT_SCAN_LIMIT:
                continue
            raw = full.read_bytes()
        except OSError:
            continue
        if not is_probably_text(raw):
            continue
        findings.extend(scan_text(raw.decode("utf-8", "replace"), path))
    return findings


def exit_code(violations: list[tuple[int, str]]) -> int:
    if not violations:
        return EXIT_CLEAN
    codes = {code for code, _ in violations}
    for code in (EXIT_POLICY, EXIT_GIT, EXIT_SECRET, EXIT_SIZE, EXIT_DENY_PATH):
        if code in codes:
            return code
    return EXIT_POLICY


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("--staged", "--tracked", "--paths"):
        print("usage: git_guard.py --staged | --tracked | --paths <path>...", file=sys.stderr)
        return EXIT_POLICY

    try:
        repo = repo_root()
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_GIT

    try:
        if argv[0] == "--staged":
            paths = staged_paths(repo)
            sizes = {p: staged_size(repo, p) for p in paths}
            violations = check_paths(repo, paths, sizes)
            violations += check_staged_secrets(repo)
        elif argv[0] == "--tracked":
            paths = tracked_paths(repo)
            violations = check_paths(repo, paths, {})
            violations += check_tracked_secrets(repo, paths)
        else:
            paths = [normalize(p) for p in argv[1:]]
            violations = check_paths(repo, paths, {})
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_GIT

    if not violations:
        print(f"OK: проверено {len(paths)} путей, нарушений нет")
        return EXIT_CLEAN

    for code, message in sorted(violations):
        print(f"VIOLATION[{code}] {message}", file=sys.stderr)
    return exit_code(violations)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
