"""Open access (REQUIRE_LOGIN=false): no sign-in, one private guest identity per browser."""
import pytest
from fastapi.testclient import TestClient

from app.db import session_scope
from app.jobs.cleanup import cleanup_expired
from app.models import MediaJob, User, UserSession
from tests.conftest import PASSWORD, make_png

ORIGIN = {"Origin": "https://testserver"}


@pytest.fixture
def open_settings(settings, monkeypatch):
    monkeypatch.setattr(settings, "require_login", False)
    return settings


def _visitor(app):
    c = TestClient(app, base_url="https://testserver")
    me = c.get("/api/auth/me")
    assert me.status_code == 200, me.text
    c.headers.update({"X-CSRF-Token": me.json()["csrf_token"], **ORIGIN})
    return c, me.json()


def test_first_visit_creates_guest_without_sign_in(app, open_settings):
    c, me = _visitor(app)
    assert me["mode"] == "open" and me["user"]["role"] == "guest"
    cookie = c.cookies.get("vd_session")
    assert cookie
    # Same browser keeps the same identity.
    assert c.get("/api/auth/me").json()["user"]["id"] == me["user"]["id"]
    r = c.post("/api/media/analyze", json={"url": "https://x.com/a/status/1"})
    assert r.status_code == 202


def test_guest_session_is_long_lived(app, open_settings):
    c, me = _visitor(app)
    with session_scope() as db:
        sess = db.query(UserSession).one()
        assert (sess.expires_at - sess.created_at).days >= 29


def test_csrf_still_enforced_for_guests(app, open_settings):
    c, _ = _visitor(app)
    del c.headers["X-CSRF-Token"]
    assert c.post("/api/media/analyze", json={"url": "https://x.com/a/status/1"}).status_code == 403


def test_guests_are_isolated_from_each_other(app, open_settings):
    a, _ = _visitor(app)
    b, _ = _visitor(app)
    job = a.post("/api/media/analyze", json={"url": "https://x.com/a/status/1"}).json()
    assert a.get(f"/api/jobs/{job['id']}").status_code == 200
    assert b.get(f"/api/jobs/{job['id']}").status_code == 404
    wm = a.post("/api/watermarks", files={"file": ("w.png", make_png(), "image/png")}).json()
    assert b.delete(f"/api/watermarks/{wm['id']}").status_code == 404
    assert b.get("/api/jobs").json()["items"] == []


def test_guests_cannot_see_admin_data(app, open_settings):
    c, _ = _visitor(app)
    assert c.get("/api/admin/status").status_code == 403
    assert c.post("/api/publishing/check").status_code == 403
    status = c.get("/api/status").json()
    assert set(status) == {"queue", "running", "storage_used_pct", "limits"}


def test_guest_creation_is_rate_limited_per_ip(app, open_settings):
    open_settings.guest_creations_per_ip_per_hour = 2
    codes = [TestClient(app, base_url="https://testserver").get("/api/auth/me").status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_server_wide_job_cap(app, open_settings):
    open_settings.max_active_jobs_total = 2
    a, _ = _visitor(app)
    b, _ = _visitor(app)
    assert a.post("/api/media/analyze", json={"url": "https://x.com/a/status/1"}).status_code == 202
    assert b.post("/api/media/analyze", json={"url": "https://x.com/a/status/2"}).status_code == 202
    r = b.post("/api/media/analyze", json={"url": "https://x.com/a/status/3"})
    assert r.status_code == 429 and r.json()["detail"]["code"] == "server_busy"


def test_admin_can_still_sign_in_in_open_mode(app, open_settings, admin):
    c = TestClient(app, base_url="https://testserver")
    r = c.post("/api/auth/login", json={"username": "admin", "password": PASSWORD}, headers=ORIGIN)
    assert r.status_code == 200 and r.json()["user"]["role"] == "admin" and r.json()["mode"] == "open"
    assert c.get("/api/admin/status").status_code == 200


def test_login_mode_does_not_create_guests(app, settings):
    c = TestClient(app, base_url="https://testserver")
    assert c.get("/api/auth/me").status_code == 401
    with session_scope() as db:
        assert db.query(User).filter_by(role="guest").count() == 0


def test_guest_can_approve_own_draft_but_not_submit(app, open_settings, monkeypatch):
    monkeypatch.setattr(open_settings, "publishing_accounts", [{"id": "ig", "network": "instagram"}])
    c, me = _visitor(app)
    from app.models import FileKind, MediaFile

    d = open_settings.media_dir / "g1"
    d.mkdir(parents=True)
    (d / "v.mp4").write_bytes(b"x")
    with session_scope() as db:
        mf = MediaFile(user_id=me["user"]["id"], kind=FileKind.VIDEO, path="g1/v.mp4", filename="v.mp4",
                       mime_type="video/mp4", size_bytes=1)
        db.add(mf)
        db.flush()
        fid = mf.id
    pj = c.post("/api/publishing/jobs", json={"media_file_id": fid, "destinations": ["ig"]}).json()
    assert c.post(f"/api/publishing/jobs/{pj['id']}/approve").json()["status"] == "approved"
    assert c.post(f"/api/publishing/jobs/{pj['id']}/submit").status_code == 403


def test_cleanup_removes_abandoned_guests_only(app, open_settings):
    from datetime import timedelta

    from app.models import utcnow

    idle, _ = _visitor(app)
    busy, _ = _visitor(app)
    busy.post("/api/media/analyze", json={"url": "https://x.com/a/status/1"})
    with session_scope() as db:
        db.query(UserSession).delete()
        db.query(User).update({User.created_at: utcnow() - timedelta(hours=2)})
    stats = cleanup_expired(open_settings)
    assert stats["guests_removed"] == 1
    with session_scope() as db:
        assert db.query(User).filter_by(role="guest").count() == 1
        assert db.query(MediaJob).count() == 1
