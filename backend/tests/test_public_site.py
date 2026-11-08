"""Behaviour that keeps a public guest site fast and fair: per-role limits, the owner's
priority lane, shared results, cancellation, remember-me and data housekeeping."""
import os

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.db import session_scope
from app.jobs import tasks
from app.jobs.cache import cache_key
from app.jobs.cleanup import cleanup_expired

from app.models import AuditLog, DownloadHistory, FileKind, JobKind, JobStatus, MediaFile, MediaJob, User, utcnow
from tests.conftest import PASSWORD
from tests.test_formats import load

ORIGIN = {"Origin": "https://testserver"}


@pytest.fixture
def open_settings(settings, monkeypatch):
    monkeypatch.setattr(settings, "require_login", False)
    return settings


def guest(app):
    c = TestClient(app, base_url="https://testserver")
    me = c.get("/api/auth/me").json()
    c.headers.update({"X-CSRF-Token": me["csrf_token"], **ORIGIN})
    return c, me


def owner(app):
    c = TestClient(app, base_url="https://testserver")
    me = c.post("/api/auth/login", json={"username": "admin", "password": PASSWORD, "remember": True},
                headers=ORIGIN).json()
    c.headers.update({"X-CSRF-Token": me["csrf_token"], **ORIGIN})
    return c, me


def completed_analysis(user_id, url="https://www.youtube.com/shorts/abcdefghijk", finished_ago=0):
    from app.media.formats import summarize_info

    with session_scope() as db:
        job = MediaJob(user_id=user_id, kind=JobKind.ANALYZE, status=JobStatus.COMPLETED, source_url=url,
                       result=summarize_info(load("youtube_short.json")), platform="youtube",
                       finished_at=utcnow() - timedelta(minutes=finished_ago))
        db.add(job)
        db.flush()
        return job.id


# ------------------------------------------------------------------ limits
def test_guest_and_owner_limits_differ(app, open_settings, admin):
    g, gme = guest(app)
    o, ome = owner(app)
    assert gme["limits"]["priority"] is False and ome["limits"]["priority"] is True
    assert gme["limits"]["max_filesize_mb"] == 300 and ome["limits"]["max_filesize_mb"] == 500
    assert ome["limits"]["retention_minutes"] == 1440 and gme["limits"]["retention_minutes"] == 60


def test_too_long_is_personalized(app, open_settings, admin):
    open_settings.guest_max_duration_seconds = 20  # fixture video is 31 s
    g, gme = guest(app)
    o, ome = owner(app)
    gid = completed_analysis(gme["user"]["id"])
    oid = completed_analysis(ome["user"]["id"])
    assert g.get(f"/api/jobs/{gid}").json()["result"]["too_long"] is True
    assert o.get(f"/api/jobs/{oid}").json()["result"]["too_long"] is False
    r = g.post("/api/media/download", json={"analysis_job_id": gid, "format_id": "best"})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "too_long"


def test_download_job_carries_guest_limits(app, open_settings, queue):
    g, gme = guest(app)
    aid = completed_analysis(gme["user"]["id"])
    job = g.post("/api/media/download", json={"analysis_job_id": aid, "format_id": "best"}).json()
    assert job["options"]["limits"] == {"max_filesize_mb": 300, "max_duration_seconds": 1200}
    assert job["options"]["retention_minutes"] == 60 and job["id"] not in queue.priority


def test_owner_jobs_use_priority_lane_and_skip_server_cap(app, open_settings, admin, queue):
    open_settings.max_active_jobs_total = 1
    g, _ = guest(app)
    o, _ = owner(app)
    assert g.post("/api/media/analyze", json={"url": "https://x.com/a/status/1"}).status_code == 202
    assert g.post("/api/media/analyze", json={"url": "https://x.com/a/status/2"}).status_code == 429
    r = o.post("/api/media/analyze", json={"url": "https://x.com/a/status/3"})
    assert r.status_code == 202 and queue.priority == [r.json()["id"]]


def test_guest_processing_duration_limit(app, open_settings):
    g, gme = guest(app)
    d = open_settings.media_dir / "long"
    d.mkdir(parents=True)
    (d / "v.mp4").write_bytes(b"x")
    with session_scope() as db:
        mf = MediaFile(user_id=gme["user"]["id"], kind=FileKind.VIDEO, path="long/v.mp4", filename="v.mp4",
                       mime_type="video/mp4", size_bytes=1, duration=900)
        db.add(mf)
        db.flush()
        fid = mf.id
    r = g.post(f"/api/media/{fid}/process", json={"aspect": "9:16"})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "too_long_to_process"


def test_queue_position(app, open_settings):
    a, _ = guest(app)
    b, _ = guest(app)
    a.post("/api/media/analyze", json={"url": "https://x.com/a/status/1"})
    jb = b.post("/api/media/analyze", json={"url": "https://x.com/a/status/2"}).json()
    assert b.get(f"/api/jobs/{jb['id']}").json()["queue_position"] == 2


# ------------------------------------------------------------------ shared results
def test_cache_key_ignores_share_parameters():
    assert cache_key("https://www.instagram.com/reel/ABC/?igsh=xyz&utm_source=ig") == \
        cache_key("https://instagram.com/reel/ABC")
    assert cache_key("https://twitter.com/u/status/1?s=20&t=abc") == cache_key("https://x.com/u/status/1")
    assert cache_key("https://youtube.com/watch?v=1") != cache_key("https://youtube.com/watch?v=2")


def test_repeat_analysis_is_instant_and_private(app, open_settings, queue):
    a, ame = guest(app)
    b, _ = guest(app)
    src = completed_analysis(ame["user"]["id"], url="https://www.instagram.com/reel/ABC/")
    r = b.post("/api/media/analyze", json={"url": "https://instagram.com/reel/ABC/?igsh=share"})
    job = r.json()
    assert r.status_code == 202 and job["status"] == "completed" and job["id"] != src
    assert job["result"]["cached"] is True and job["result"]["title"]
    assert queue.enqueued == []  # no platform request at all
    assert a.get(f"/api/jobs/{job['id']}").status_code == 404  # still private to b


def test_stale_analysis_is_not_reused(app, open_settings, queue):
    a, ame = guest(app)
    b, _ = guest(app)
    completed_analysis(ame["user"]["id"], url="https://x.com/u/status/9", finished_ago=60)
    assert b.post("/api/media/analyze", json={"url": "https://x.com/u/status/9"}).json()["status"] == "queued"


def _stored_download(settings, user_id, analysis_id, format_id="137"):
    d = settings.media_dir / f"dl-{user_id}"
    d.mkdir(parents=True)
    (d / "video.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"v" * 1000)
    with session_scope() as db:
        an = db.get(MediaJob, analysis_id)
        job = MediaJob(user_id=user_id, kind=JobKind.DOWNLOAD, status=JobStatus.COMPLETED, parent_job_id=an.id,
                       source_url=an.source_url, options={"format": {"format_id": format_id, "label": "1920p"}},
                       finished_at=utcnow())
        db.add(job)
        db.flush()
        mf = MediaFile(user_id=user_id, job_id=job.id, kind=FileKind.VIDEO, path=f"dl-{user_id}/video.mp4",
                       filename="clip.mp4", mime_type="video/mp4", size_bytes=1012, acodec="aac",
                       expires_at=utcnow() + timedelta(minutes=50))
        db.add(mf)
        db.flush()
        job.result = {"media_file_id": mf.id}
        return mf.id, settings.media_dir / mf.path


def test_repeat_download_shares_file_without_extra_disk(app, open_settings, queue):
    a, ame = guest(app)
    b, bme = guest(app)
    a_analysis = completed_analysis(ame["user"]["id"])
    a_file, a_path = _stored_download(open_settings, ame["user"]["id"], a_analysis)
    b_analysis = b.post("/api/media/analyze", json={"url": "https://youtube.com/shorts/abcdefghijk"}).json()
    r = b.post("/api/media/download", json={"analysis_job_id": b_analysis["id"], "format_id": "137"})
    job = r.json()
    assert job["status"] == "completed" and job["result"]["cached"] is True and queue.enqueued == []
    b_file = job["result"]["media_file_id"]
    assert b_file != a_file
    assert b.get(f"/api/media/{b_file}/file").content == a_path.read_bytes()
    assert a.get(f"/api/media/{b_file}/file").status_code == 404
    with session_scope() as db:
        b_path = open_settings.media_dir / db.get(MediaFile, b_file).path
    assert os.stat(b_path).st_ino == os.stat(a_path).st_ino  # hard link: no extra space
    # Deleting one visitor's copy leaves the other's intact.
    a.delete(f"/api/media/{a_file}")
    assert b.get(f"/api/media/{b_file}/file").status_code == 200
    assert b.get("/api/media/history").json()["items"][0]["status"] == "completed"


def test_different_format_is_not_shared(app, open_settings, queue):
    a, ame = guest(app)
    b, _ = guest(app)
    _stored_download(open_settings, ame["user"]["id"], completed_analysis(ame["user"]["id"]), format_id="137")
    b_analysis = b.post("/api/media/analyze", json={"url": "https://youtube.com/shorts/abcdefghijk"}).json()
    job = b.post("/api/media/download", json={"analysis_job_id": b_analysis["id"], "format_id": "18"}).json()
    assert job["status"] == "queued" and queue.enqueued == [job["id"]]


# ------------------------------------------------------------------ cancellation
def test_cancel_queued_job(app, open_settings, queue):
    g, _ = guest(app)
    job = g.post("/api/media/analyze", json={"url": "https://x.com/a/status/1"}).json()
    r = g.post(f"/api/jobs/{job['id']}/cancel")
    assert r.status_code == 200
    j = g.get(f"/api/jobs/{job['id']}").json()
    assert j["status"] == "failed" and j["error"]["code"] == "cancelled"
    tasks.run_job(job["id"])  # a worker picking it up later does nothing
    assert g.get(f"/api/jobs/{job['id']}").json()["error"]["code"] == "cancelled"
    assert g.post(f"/api/jobs/{job['id']}/cancel").status_code == 409


def test_cancel_running_download_stops_ytdlp(app, open_settings, queue, monkeypatch):
    g, gme = guest(app)
    aid = completed_analysis(gme["user"]["id"])
    job = g.post("/api/media/download", json={"analysis_job_id": aid, "format_id": "best"}).json()
    events = []

    def fake(request, timeout, on_event=None, settings=None):
        import time as _t

        for i in range(50):
            if i == 2:  # visitor presses Cancel mid-download
                with session_scope() as db:
                    db.get(MediaJob, job["id"]).cancel_requested = True
            events.append(i)
            on_event({"type": "progress", "stream": 0, "downloaded": i, "total": 100})
            _t.sleep(0.25)
        raise AssertionError("should have been cancelled")

    monkeypatch.setattr(tasks, "run_ytdlp", fake)
    tasks.run_job(job["id"])
    j = g.get(f"/api/jobs/{job['id']}").json()
    assert j["status"] == "failed" and j["error"]["code"] == "cancelled" and len(events) < 15
    assert g.get("/api/media/history").json()["items"] == []  # cancellations aren't failures


# ------------------------------------------------------------------ owner sessions, site info, housekeeping
def test_remember_me_session_is_long(app, open_settings, admin):
    owner(app)
    with session_scope() as db:
        from app.models import UserSession

        sess = db.query(UserSession).filter_by(user_id=admin).one()
        assert sess.persistent and (sess.expires_at - sess.created_at).days >= 29


def test_login_replaces_guest_session(app, open_settings, admin):
    c, gme = guest(app)
    r = c.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    assert r.json()["user"]["role"] == "admin"
    assert c.get("/api/auth/me").json()["user"]["role"] == "admin"


def test_site_info_is_public(app, settings):
    settings.contact_email = "hello@example.com"
    r = TestClient(app, base_url="https://testserver").get("/api/site")
    body = r.json()
    assert r.status_code == 200 and body["contact_email"] == "hello@example.com"
    assert body["guest_limits"]["retention_minutes"] == 60 and "YouTube" in body["platforms"]


def test_abandoned_guest_data_is_purged(app, open_settings, admin):
    g, gme = guest(app)
    gid = gme["user"]["id"]
    aid = completed_analysis(gid)
    _, path = _stored_download(open_settings, gid, aid)
    with session_scope() as db:
        db.add(DownloadHistory(user_id=gid, job_id=aid, kind="download", status="completed"))
        db.add(AuditLog(user_id=gid, action="analyze"))
        from app.models import UserSession

        db.query(UserSession).filter_by(user_id=gid).delete()
        db.query(User).filter_by(id=gid).update({User.created_at: utcnow() - timedelta(hours=2)})
    stats = cleanup_expired(open_settings)
    assert stats["guests_removed"] == 1 and not path.exists()
    with session_scope() as db:
        assert db.get(User, gid) is None and db.get(User, admin) is not None
        assert db.query(MediaJob).filter_by(user_id=gid).count() == 0
        assert db.query(AuditLog).filter_by(action="analyze").one().user_id is None


def test_old_audit_rows_are_removed(app, open_settings):
    with session_scope() as db:
        db.add(AuditLog(action="old", created_at=utcnow() - timedelta(days=200)))
        db.add(AuditLog(action="new"))
    assert cleanup_expired(open_settings)["audit_rows_removed"] == 1


def test_admin_status_has_daily_stats(app, open_settings, admin):
    o, _ = owner(app)
    body = o.get("/api/admin/status").json()
    assert set(body["last_24h"]) == {"completed", "failures_by_reason", "served_from_cache", "active_visitors"}


def test_storage_counts_hardlinks_once(settings, tmp_path):
    from app.media.storage import dir_size

    a = tmp_path / "a.bin"
    a.write_bytes(b"x" * 1000)
    os.link(a, tmp_path / "b.bin")
    assert dir_size(tmp_path) == 1000
