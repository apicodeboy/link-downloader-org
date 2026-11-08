from datetime import timedelta

import pytest

from app.db import session_scope
from app.models import AuditLog, UserSession, utcnow
from app.security.passwords import check_password_strength, hash_password, verify_password
from tests.conftest import PASSWORD

ORIGIN = {"Origin": "https://testserver"}

# Every endpoint except /api/health and /api/auth/login must require a session.
PROTECTED = [
    ("get", "/api/auth/me"), ("post", "/api/auth/logout"),
    ("post", "/api/media/analyze"), ("post", "/api/media/download"), ("get", "/api/media/history"),
    ("get", "/api/media/abc"), ("get", "/api/media/abc/file"), ("delete", "/api/media/abc"),
    ("post", "/api/media/abc/process"), ("get", "/api/jobs"), ("get", "/api/jobs/abc"), ("post", "/api/jobs/abc/cancel"),
    ("get", "/api/watermarks"), ("post", "/api/watermarks"), ("delete", "/api/watermarks/abc"),
    ("get", "/api/presets"), ("post", "/api/presets"), ("put", "/api/presets/1"), ("delete", "/api/presets/1"),
    ("get", "/api/admin/status"), ("get", "/api/status"), ("get", "/api/publishing/config"), ("post", "/api/publishing/check"),
    ("get", "/api/publishing/jobs"), ("post", "/api/publishing/jobs"), ("patch", "/api/publishing/jobs/1"),
    ("post", "/api/publishing/jobs/1/approve"), ("post", "/api/publishing/jobs/1/submit"),
    ("post", "/api/publishing/jobs/1/cancel"), ("get", "/api/publishing/jobs/1/package"),
]


@pytest.mark.parametrize("method,path", PROTECTED)
def test_endpoints_require_login(anon_client, method, path):
    r = getattr(anon_client, method)(path, headers=ORIGIN)
    assert r.status_code == 401, (path, r.status_code, r.text)
    assert r.json()["detail"]["code"] == "not_authenticated"


def test_every_route_is_covered_by_auth_test(app):
    public = {("get", "/api/health"), ("post", "/api/auth/login"), ("get", "/api/site")}
    covered = {(m, p.replace("abc", "{file_id}").replace("/1", "/{id}")) for m, p in PROTECTED}
    for path, ops in app.openapi()["paths"].items():
        for method in ops:
            norm = path.replace("{job_id}", "{id}").replace("{preset_id}", "{id}")
            norm = norm.replace("/api/jobs/{id}", "/api/jobs/{file_id}")
            key = (method, norm)
            assert key in public or key in covered, f"untested route {method.upper()} {path}"


def test_health_is_public_and_minimal(anon_client):
    r = anon_client.get("/api/health")
    assert r.status_code == 200
    assert set(r.json()) == {"status", "checks"}


def test_login_success_sets_hardened_cookie(anon_client, admin):
    r = anon_client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD}, headers=ORIGIN)
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie
    assert r.json()["user"]["username"] == "admin" and len(r.json()["csrf_token"]) > 20
    with session_scope() as db:
        assert db.query(UserSession).count() == 1
        token_hash = db.query(UserSession).one().token_hash
    assert anon_client.cookies.get("vd_session") not in token_hash  # only a hash is stored


def test_login_wrong_password_and_unknown_user(anon_client, admin):
    for body in ({"username": "admin", "password": "nope"}, {"username": "ghost", "password": "nope"}):
        r = anon_client.post("/api/auth/login", json=body, headers=ORIGIN)
        assert r.status_code == 401 and r.json()["detail"]["code"] == "invalid_credentials"
    with session_scope() as db:
        assert db.query(AuditLog).filter_by(action="login", success=False).count() == 2


def test_account_lockout(anon_client, admin):
    for _ in range(5):
        anon_client.post("/api/auth/login", json={"username": "admin", "password": "bad"}, headers=ORIGIN)
    r = anon_client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD}, headers=ORIGIN)
    assert r.status_code == 429 and r.json()["detail"]["code"] == "account_locked"


def test_login_from_foreign_origin_is_rejected(anon_client, admin):
    r = anon_client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD},
                         headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_csrf_token_required_for_mutations(client):
    good = client.headers["X-CSRF-Token"]
    del client.headers["X-CSRF-Token"]
    r = client.post("/api/media/analyze", json={"url": "https://x.com/a/status/1"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "csrf_failed"
    r = client.post("/api/media/analyze", json={"url": "https://x.com/a/status/1"}, headers={"X-CSRF-Token": "wrong"})
    assert r.status_code == 403
    r = client.post("/api/media/analyze", json={"url": "https://x.com/a/status/1"},
                    headers={"X-CSRF-Token": good, "Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "bad_origin"
    r = client.post("/api/media/analyze", json={"url": "https://x.com/a/status/1"}, headers={"X-CSRF-Token": good})
    assert r.status_code == 202


def test_logout_revokes_session(client):
    assert client.get("/api/auth/me").status_code == 200
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_expired_and_idle_sessions_are_rejected(client):
    with session_scope() as db:
        db.query(UserSession).update({UserSession.last_seen_at: utcnow() - timedelta(hours=5)})
    assert client.get("/api/auth/me").status_code == 401


def test_login_rate_limit(app, anon_client, admin, settings):
    settings.login_rate_limit_per_minute = 3
    codes = [anon_client.post("/api/auth/login", json={"username": "x", "password": "y"}, headers=ORIGIN).status_code
             for _ in range(5)]
    assert codes[:3] == [401, 401, 401] and codes[3:] == [429, 429]


def test_password_hashing():
    h = hash_password("Some-Long-Passw0rd")
    assert h.startswith("scrypt$") and verify_password("Some-Long-Passw0rd", h)
    assert not verify_password("some-long-passw0rd", h)
    assert not verify_password("x", "garbage")
    assert check_password_strength("short") is not None
    assert check_password_strength("Correct-Horse-Battery-9") is None


def test_security_headers(anon_client):
    r = anon_client.get("/api/health")
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'none'" in r.headers["content-security-policy"]
