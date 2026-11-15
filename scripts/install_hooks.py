#!/usr/bin/env python3
"""Подключает .githooks как core.hooksPath и делает хуки исполняемыми."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / ".githooks"


def main() -> int:
    if not (ROOT / ".git").exists():
        print("ERROR: .git не найден. Сначала выполните git init.", file=sys.stderr)
        return 1
    if not HOOKS.is_dir():
        print("ERROR: .githooks не найден.", file=sys.stderr)
        return 1

    for hook in ("pre-commit", "pre-push"):
        path = HOOKS / hook
        if not path.exists():
            print(f"ERROR: нет хука {path}", file=sys.stderr)
            return 1
        if os.name == "posix":
            mode = path.stat().st_mode
            path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n"))

    proc = subprocess.run(
        ["git", "config", "core.hooksPath", ".githooks"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(f"ERROR: git config failed: {proc.stderr.strip()}", file=sys.stderr)
        return 1

    print("OK: core.hooksPath=.githooks, хуки готовы")
    return 0


if __name__ == "__main__":
    sys.exit(main())
