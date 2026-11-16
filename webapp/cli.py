from __future__ import annotations

import argparse
import getpass
import sys

from webapp.db import SessionLocal
from webapp.models.user import User
from webapp.services import audit, sessions
from webapp.services.security import hash_password, verify_password


def _prompt_password(label: str) -> str:
    first = getpass.getpass(label)
    second = getpass.getpass("Повторите пароль: ")
    if first != second:
        raise SystemExit("ERROR: пароли не совпадают")
    if len(first) < 12:
        raise SystemExit("ERROR: пароль короче 12 символов")
    return first


def admin_passwd(args: argparse.Namespace) -> int:
    db = SessionLocal()
    try:
        admin = db.get(User, 0)
        if admin is None:
            print("ERROR: администратор ID 0 не найден", file=sys.stderr)
            return 1
        if not args.from_env:
            current = getpass.getpass("Текущий пароль admin: ")
            if not verify_password(admin.password_hash, current):
                print("ERROR: неверный текущий пароль", file=sys.stderr)
                return 1
            new_password = _prompt_password("Новый пароль admin: ")
        else:
            if not args.confirm:
                print("ERROR: добавьте --confirm для применения ADM_PASSW из .env", file=sys.stderr)
                return 1
            from webapp.config import get_settings

            new_password = get_settings().adm_passw.get_secret_value()
            if len(new_password) < 12:
                print("ERROR: ADM_PASSW короче 12 символов", file=sys.stderr)
                return 1

        admin.password_hash = hash_password(new_password)
        sessions.revoke_user_sessions(db, admin.id)
        audit.log_action(db, "admin.password_changed", actor_id=admin.id)
        db.commit()
        print("OK: пароль admin обновлён, все сессии отозваны")
        return 0
    finally:
        db.close()


def stats(args: argparse.Namespace) -> int:
    from sqlalchemy import func, select

    from webapp.models.content import Post
    from webapp.models.support import Ticket
    from webapp.models.system import Job

    db = SessionLocal()
    try:
        print("users:", db.execute(select(func.count(User.id))).scalar_one())
        print("tickets:", db.execute(select(func.count(Ticket.id))).scalar_one())
        print("posts:", db.execute(select(func.count(Post.id))).scalar_one())
        print("jobs:", db.execute(select(func.count(Job.id))).scalar_one())
        return 0
    finally:
        db.close()


def publish_due(args: argparse.Namespace) -> int:
    from webapp.services.scheduler import publish_due as run_due

    db = SessionLocal()
    try:
        results = run_due(db)
        if not results:
            print("Нет постов, готовых к публикации по расписанию")
            return 0
        for post_id, outcomes in results:
            states = ", ".join(f"{item.platform}={item.status}" for item in outcomes)
            print(f"post {post_id}: {states}")
        return 0
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="webapp.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("admin-passwd", help="сменить пароль администратора ID 0")
    p.add_argument("--from-env", action="store_true", help="взять новый пароль из ADM_PASSW")
    p.add_argument("--confirm", action="store_true", help="подтвердить применение ADM_PASSW")
    p.set_defaults(func=admin_passwd)

    s = sub.add_parser("stats", help="показать счётчики")
    s.set_defaults(func=stats)

    due = sub.add_parser("publish-due", help="опубликовать посты с наступившим scheduled_at")
    due.set_defaults(func=publish_due)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
