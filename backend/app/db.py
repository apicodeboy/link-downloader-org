"""Database engine and session handling.

SQLAlchemy keeps the code database-agnostic: switching DATABASE_URL to a PostgreSQL URL
(postgresql+psycopg://...) and running Alembic migrations is all a migration needs.
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None
_engine_url: str | None = None
_engine_pid: int | None = None


def _make_engine(url: str) -> Engine:
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")  # API and worker write concurrently
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.close()
    return engine


def init_engine(url: str | None = None) -> Engine:
    global _engine, _SessionLocal, _engine_url, _engine_pid
    url = url or get_settings().database_url
    if _engine is not None:
        _engine.dispose(close=_engine_pid == os.getpid())
    _engine_url, _engine_pid = url, os.getpid()
    if url.startswith("sqlite:///./"):
        get_settings().data_dir.mkdir(parents=True, exist_ok=True)
    _engine = _make_engine(url)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def _ensure_engine() -> None:
    # RQ forks a child per job; connections must never be shared across processes.
    if _engine is None:
        init_engine()
    elif _engine_pid != os.getpid():
        init_engine(_engine_url)


def get_engine() -> Engine:
    _ensure_engine()
    assert _engine is not None
    return _engine


def SessionLocal() -> Session:
    _ensure_engine()
    assert _SessionLocal is not None
    return _SessionLocal()


@contextmanager
def session_scope() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_all() -> None:
    from . import models  # noqa: F401  (register tables)

    Base.metadata.create_all(get_engine())
