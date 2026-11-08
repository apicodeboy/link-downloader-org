"""Admin command line.

    python -m app.cli init-db                 create/upgrade database tables (Alembic)
    python -m app.cli create-admin USERNAME   create an administrator (prompts for password)
    python -m app.cli reset-password USERNAME
    python -m app.cli cleanup                 delete expired media now
    python -m app.cli check                   verify FFmpeg, yt-dlp, Redis and database
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

from sqlalchemy import func, select

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _read_password(from_stdin: bool) -> str:
    from .security.passwords import check_password_strength

    if from_stdin:
        pw = sys.stdin.readline().rstrip("\n")
    else:
        pw = getpass.getpass("Password: ")
        if getpass.getpass("Repeat password: ") != pw:
            sys.exit("Passwords do not match.")
    problem = check_password_strength(pw)
    if problem:
        sys.exit(problem)
    return pw


def cmd_init_db(_args) -> None:
    from alembic import command
    from alembic.config import Config

    from .config import get_settings

    s = get_settings()
    s.ensure_dirs()
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", s.database_url)
    command.upgrade(cfg, "head")
    print("Database is up to date.")


def cmd_create_admin(args) -> None:
    from .db import session_scope
    from .models import User
    from .security.passwords import hash_password

    with session_scope() as db:
        if db.scalar(select(User).where(func.lower(User.username) == args.username.lower())):
            sys.exit(f"User {args.username} already exists. Use reset-password instead.")
        pw = _read_password(args.password_stdin)
        db.add(User(username=args.username, password_hash=hash_password(pw), role="admin"))
    print(f"Administrator {args.username} created.")


def cmd_reset_password(args) -> None:
    from .db import session_scope
    from .models import User
    from .security.passwords import hash_password
    from .security.sessions import revoke_all_for_user

    with session_scope() as db:
        user = db.scalar(select(User).where(func.lower(User.username) == args.username.lower()))
        if user is None:
            sys.exit(f"No user named {args.username}.")
        user.password_hash = hash_password(_read_password(args.password_stdin))
        user.failed_login_count, user.locked_until = 0, None
        db.flush()
        revoke_all_for_user(db, user.id)
    print(f"Password for {args.username} reset; existing sessions signed out.")


def cmd_cleanup(_args) -> None:
    from .jobs.cleanup import cleanup_expired

    print(json.dumps(cleanup_expired()))


def cmd_check(_args) -> None:
    from sqlalchemy import text

    from .config import get_settings
    from .db import get_engine
    from .jobs.queue import RQJobQueue
    from .media.ffmpeg import FFmpeg
    from .media.ytdlp import ytdlp_version

    s = get_settings()
    ff = FFmpeg(s)
    results = {"yt_dlp": ytdlp_version(), "ffmpeg": ff.version() or "MISSING",
               "ffmpeg_encoder": " ".join(ff.video_encoder_args()[:2]) if ff.available() else "n/a"}
    try:
        with get_engine().connect() as c:
            c.execute(text("SELECT 1"))
        results["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        results["database"] = f"ERROR {exc}"
    results["redis"] = "ok" if RQJobQueue(s).ping() else "UNREACHABLE"
    for k, v in results.items():
        print(f"{k:16} {v}")
    if "MISSING" in results.values() or results["redis"] != "ok" or results["database"] != "ok":
        sys.exit(1)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="python -m app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db").set_defaults(fn=cmd_init_db)
    for name, fn in (("create-admin", cmd_create_admin), ("reset-password", cmd_reset_password)):
        sp = sub.add_parser(name)
        sp.add_argument("username")
        sp.add_argument("--password-stdin", action="store_true", help="read the password from standard input")
        sp.set_defaults(fn=fn)
    sub.add_parser("cleanup").set_defaults(fn=cmd_cleanup)
    sub.add_parser("check").set_defaults(fn=cmd_check)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
