"""Server-side sessions. The cookie holds a random token; the database stores its SHA-256."""
from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import User, UserSession, utcnow


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _ttl(user: User) -> timedelta:
    s = get_settings()
    if user.role == "guest":
        return timedelta(days=s.guest_session_days)
    return timedelta(hours=s.session_ttl_hours)


def _idle(user: User) -> timedelta:
    s = get_settings()
    # Guests keep their history for the whole session lifetime; accounts time out when idle.
    if user.role == "guest":
        return timedelta(days=s.guest_session_days)
    return timedelta(minutes=s.session_idle_minutes)


def create_session(db: Session, user: User, ip: str | None, user_agent: str | None) -> tuple[str, UserSession]:
    token = secrets.token_urlsafe(32)
    sess = UserSession(
        token_hash=_hash(token),
        csrf_token=secrets.token_urlsafe(32),
        user_id=user.id,
        ip=ip,
        user_agent=(user_agent or "")[:255],
        expires_at=utcnow() + _ttl(user),
    )
    db.add(sess)
    db.commit()
    return token, sess


def load_session(db: Session, token: str | None) -> UserSession | None:
    if not token or len(token) > 128:
        return None
    sess = db.scalar(select(UserSession).where(UserSession.token_hash == _hash(token)))
    if sess is None:
        return None
    now = utcnow()
    if sess.expires_at <= now or sess.last_seen_at + _idle(sess.user) <= now or not sess.user.is_active:
        db.delete(sess)
        db.commit()
        return None
    if (now - sess.last_seen_at).total_seconds() > 60:
        sess.last_seen_at = now
        db.commit()
    return sess


def revoke_session(db: Session, token: str | None) -> None:
    if token:
        db.execute(delete(UserSession).where(UserSession.token_hash == _hash(token)))
        db.commit()


def revoke_all_for_user(db: Session, user_id: int) -> None:
    db.execute(delete(UserSession).where(UserSession.user_id == user_id))
    db.commit()


def session_max_age(user: User) -> int:
    return int(_ttl(user).total_seconds())


def purge_expired(db: Session) -> int:
    res = db.execute(delete(UserSession).where(UserSession.expires_at <= utcnow()))
    db.commit()
    return res.rowcount or 0
