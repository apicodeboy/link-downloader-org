"""Login, logout and current-session endpoints."""
from __future__ import annotations

import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import audit, client_ip
from ..config import get_settings
from ..db import get_db
from ..deps import api_error, check_origin, rate_limited, require_csrf
from ..limits import limits_for
from ..models import User, UserSession, utcnow
from ..schemas import LoginIn
from ..security.passwords import DUMMY_HASH, verify_password
from ..security.sessions import create_session, load_session, revoke_session, session_max_age

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _me(sess: UserSession) -> dict:
    u = sess.user
    return {"user": {"id": u.id, "username": u.username, "role": u.role}, "csrf_token": sess.csrf_token,
            "expires_at": sess.expires_at.isoformat(),
            "mode": "login" if get_settings().require_login else "open",
            "limits": limits_for(u.role).as_dict()}


def _set_cookie(response: Response, token: str, user: User, persistent: bool = False) -> None:
    s = get_settings()
    response.set_cookie(
        s.session_cookie_name, token, max_age=session_max_age(user, persistent), httponly=True,
        secure=s.session_cookie_secure, samesite="strict", path="/",
    )


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
    # Replace any guest session this browser had.
    revoke_session(db, request.cookies.get(s.session_cookie_name))
    token, sess = create_session(db, user, client_ip(request), request.headers.get("user-agent"),
                                 persistent=body.remember)
    _set_cookie(response, token, user, body.remember)
    audit(db, request, "login", user_id=user.id, remember=body.remember)
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
def me(request: Request, response: Response, db: Session = Depends(get_db)):
    """Current identity. In open mode, a first-time visitor gets a guest identity here."""
    s = get_settings()
    sess = load_session(db, request.cookies.get(s.session_cookie_name))
    if sess is not None:
        return _me(sess)
    if s.require_login:
        raise api_error(401, "not_authenticated", "Please sign in.")
    allowed, reset = request.app.state.rate_limiter.hit(
        "guest", client_ip(request) or "unknown", s.guest_creations_per_ip_per_hour, window=3600)
    if not allowed:
        raise api_error(429, "rate_limited", f"Too many new visitors from your network. Try again in "
                                             f"{max(1, reset // 60)} minutes.", headers={"Retry-After": str(reset)})
    guest = User(username=f"guest-{secrets.token_hex(6)}", password_hash="!", role="guest")
    db.add(guest)
    db.commit()
    token, sess = create_session(db, guest, client_ip(request), request.headers.get("user-agent"))
    _set_cookie(response, token, guest)
    audit(db, request, "guest_created", user_id=guest.id)
    return _me(sess)
