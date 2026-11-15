#!/usr/bin/env python3
"""Создаёт роль и базу PostgreSQL по DATABASE_URL из .env.

Запускать после установки PostgreSQL. Пароль суперпользователя postgres
вводится интерактивно и нигде не сохраняется.
"""

from __future__ import annotations

import getpass
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"


def read_database_url() -> str:
    if not ENV.exists():
        raise SystemExit("ERROR: .env не найден. Сначала scripts/migrate_env.py")
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("ERROR: DATABASE_URL не найден в .env")


def main() -> int:
    url = read_database_url().replace("postgresql+psycopg://", "postgresql://")
    parts = urlsplit(url)
    app_user = unquote(parts.username or "")
    app_password = unquote(parts.password or "")
    db_name = (parts.path or "/rompetr").lstrip("/")
    host = parts.hostname or "127.0.0.1"
    port = parts.port or 5432

    if not app_user or not app_password or app_password == "change-me":
        raise SystemExit("ERROR: задайте реальный пароль rompetr_app в DATABASE_URL (.env)")

    super_password = getpass.getpass("Пароль пользователя postgres: ")
    admin_dsn = f"host={host} port={port} dbname=postgres user=postgres password={super_password}"

    try:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (app_user,))
                if cur.fetchone():
                    cur.execute(
                        sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD %s").format(
                            sql.Identifier(app_user)
                        ),
                        (app_password,),
                    )
                    print(f"OK: роль {app_user} обновлена")
                else:
                    cur.execute(
                        sql.SQL("CREATE ROLE {} WITH LOGIN PASSWORD %s").format(
                            sql.Identifier(app_user)
                        ),
                        (app_password,),
                    )
                    print(f"OK: роль {app_user} создана")

                cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
                if cur.fetchone():
                    print(f"OK: база {db_name} уже существует")
                else:
                    cur.execute(
                        sql.SQL("CREATE DATABASE {} OWNER {}").format(
                            sql.Identifier(db_name), sql.Identifier(app_user)
                        )
                    )
                    print(f"OK: база {db_name} создана")
    except psycopg.Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print("Дальше: .venv\\Scripts\\python -m alembic upgrade head")
    return 0


if __name__ == "__main__":
    sys.exit(main())
