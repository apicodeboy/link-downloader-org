"""Shared FastAPI dependencies: authentication, CSRF, rate limiting, errors."""
from __future__ import annotations

import hmac
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .audit import client_ip
from .config import get_settings
from .db import get_db
from .models import User, UserSession
from .security.sessions import load_session

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def api_error(status: int, code: str, message: str, headers: dict | None = None) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message}, headers=headers)


def get_session(request: Request, db: Session = Depends(get_db)) -> UserSession:
    token = request.cookies.get(get_settings().session_cookie_name)
    sess = load_session(db, token)
    if sess is None:
        raise api_error(401, "not_authenticated", "Please sign in.")
    request.state.user_id = sess.user_id
    return sess


def current_user(sess: UserSession = Depends(get_session)) -> User:
    return sess.user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise api_error(403, "forbidden", "Administrator access is required.")
    return user


def check_origin(request: Request) -> None:
    """Reject cross-site browser requests. Non-browser clients send no Origin header and
    are still bound by the CSRF token check."""
    origin = request.headers.get("origin")
    if not origin:
        referer = request.headers.get("referer")
        if referer:
            p = urlsplit(referer)
            origin = f"{p.scheme}://{p.netloc}"
    if not origin:
        return
    origin = origin.rstrip("/")
    allowed = get_settings().origins
    if allowed:
        ok = origin in allowed
    else:
        host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
        ok = urlsplit(origin).netloc == host
    if not ok:
        raise api_error(403, "bad_origin", "Request blocked: it came from a different website.")


def require_csrf(request: Request, sess: UserSession = Depends(get_session)) -> UserSession:
    if request.method in SAFE_METHODS:
        return sess
    check_origin(request)
    token = request.headers.get("x-csrf-token", "")
    if not token or not hmac.compare_digest(token, sess.csrf_token):
        raise api_error(403, "csrf_failed", "Security token missing or expired. Reload the page and try again.")
    return sess


def rate_limited(bucket: str, setting_name: str):
    def dependency(request: Request) -> None:
        limit = int(getattr(get_settings(), setting_name))
        allowed, reset = request.app.state.rate_limiter.hit(bucket, client_ip(request) or "unknown", limit)
        if not allowed:
            raise api_error(429, "rate_limited", f"Too many requests. Try again in {reset} seconds.",
                            headers={"Retry-After": str(reset)})

    return dependency
