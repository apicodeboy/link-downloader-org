"""FastAPI application factory."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .config import Settings, get_settings
from .db import init_engine
from .jobs.queue import JobQueue, RQJobQueue
from .routers import assets, auth, health, jobs, media, publishing
from .security.ratelimit import RateLimiter

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, queue: JobQueue | None = None,
               rate_limiter: RateLimiter | None = None) -> FastAPI:
    s = settings or get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if s.is_production and not s.session_cookie_secure:
        raise RuntimeError("SESSION_COOKIE_SECURE must be true in production")
    s.ensure_dirs()
    init_engine(s.database_url)

    docs = not s.is_production
    app = FastAPI(
        title=s.app_name, version="1.0.0",
        docs_url="/api/docs" if docs else None, redoc_url=None,
        openapi_url="/api/openapi.json" if docs else None,
    )
    if queue is None:
        queue = RQJobQueue(s)
    app.state.queue = queue
    if rate_limiter is None:
        redis_client = getattr(queue, "redis", None)
        rate_limiter = RateLimiter(redis_client)
    app.state.rate_limiter = rate_limiter

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if not request.url.path.startswith("/api/docs"):
            response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        if request.url.path.startswith("/api/") and "cache-control" not in response.headers:
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(p) for p in first.get("loc", [])[1:]) or "request"
        return JSONResponse(status_code=422, content={"detail": {
            "code": "invalid_request", "message": f"{field}: {first.get('msg', 'invalid value')}"}})

    for r in (health.router, auth.router, media.router, jobs.router, assets.router, publishing.router):
        app.include_router(r)
    return app
