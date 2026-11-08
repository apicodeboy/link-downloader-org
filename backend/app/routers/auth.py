"""Login, logout and current-session endpoints."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import audit, client_ip
from ..config import get_settings
from ..db import get_db
from ..deps import api_error, check_origin, get_session, rate_limited, require_csrf
from ..models import User, UserSession, utcnow
from ..schemas import LoginIn
from ..security.passwords import DUMMY_HASH, verify_password
from ..security.sessions import create_session, revoke_session

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _me(sess: UserSession) -> dict:
    u = sess.user
    return {"user": {"id": u.id, "username": u.username, "role": u.role}, "csrf_token": sess.csrf_token,
            "expires_at": sess.expires_at.isoformat()}


@router.post("/login", dependencies=[Depends(rate_limited("login", "login_rate_limit_per_minute"))])
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    check_origin(request)
    s = get_settings()
    user = db.scalar(select(User).where(func.lower(User.username) == body.username.strip().lower()))
    now = utcnow()
    if user is not None and user.locked_until and user.locked_until > now:
        verify_password(body.password, DUMMY_HASH)
        audit(db, request, "login", user_id=user.id, success=False, reason="locked")
        minutes = max(1, int((user.locked_until - now).total_seconds() // 60) + 1)
        raise api_error(429, "account_locked", f"Too many failed sign-in attempts. Try again in {minutes} minutes.")

    ok = verify_password(body.password, user.password_hash if user else DUMMY_HASH)
    if not ok or user is None or not user.is_active:
        if user is not None:
            user.failed_login_count = (user.failed_login_count or 0) + 1
            if user.failed_login_count >= s.login_max_failures:
                user.locked_until = now + timedelta(minutes=s.login_lockout_minutes)
                user.failed_login_count = 0
            db.commit()
        audit(db, request, "login", user_id=user.id if user else None, success=False,
              username=body.username[:64])
        raise api_error(401, "invalid_credentials", "Incorrect username or password.")

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    db.commit()
    token, sess = create_session(db, user, client_ip(request), request.headers.get("user-agent"))
    response.set_cookie(
        s.session_cookie_name, token, max_age=s.session_ttl_hours * 3600, httponly=True,
        secure=s.session_cookie_secure, samesite="strict", path="/",
    )
    audit(db, request, "login", user_id=user.id)
    return _me(sess)


@router.post("/logout")
def logout(request: Request, response: Response, sess: UserSession = Depends(require_csrf),
           db: Session = Depends(get_db)):
    s = get_settings()
    user_id = sess.user_id
    revoke_session(db, request.cookies.get(s.session_cookie_name))
    response.delete_cookie(s.session_cookie_name, path="/", secure=s.session_cookie_secure,
                           httponly=True, samesite="strict")
    audit(db, request, "logout", user_id=user_id)
    return {"ok": True}


@router.get("/me")
def me(sess: UserSession = Depends(get_session)):
    return _me(sess)
