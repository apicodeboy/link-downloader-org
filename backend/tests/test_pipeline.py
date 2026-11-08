"""End-to-end job pipeline with yt-dlp replaced by a fake that returns local sample media."""
import shutil

import pytest

from app.db import session_scope
from app.jobs import tasks
from app.media.errors import MediaError
from app.models import DownloadHistory, MediaFile, MediaJob
from tests.conftest import needs_ffmpeg
from tests.test_formats import load


@pytest.fixture
def fake_ytdlp(monkeypatch, sample_media):
    calls = []

    def fake(request, timeout, on_event=None, settings=None):
        calls.append(request)
        from pathlib import Path

        from app.media.formats import summarize_info

        workdir = Path(request["workdir"])
        workdir.mkdir(parents=True, exist_ok=True)
        info = load("twitter.json")
        if request["mode"] == "analyze":
            shutil.copy(sample_media["jpg"], workdir / "thumb.jpg")
            return {"summary": summarize_info(info), "thumbnail": str(workdir / "thumb.jpg"), "warnings": []}
        if on_event:
            on_event({"type": "progress", "stream": 0, "downloaded": 50, "total": 100})
        out = workdir / "video.mp4"
        shutil.copy(sample_media["mp4"], out)
        return {"filepath": str(out), "summary": summarize_info(info), "warnings": []}

    monkeypatch.setattr(tasks, "run_ytdlp", fake)
    monkeypatch.setattr(tasks, "resolve_redirects", lambda url, s=None: url)
    return calls


@needs_ffmpeg
def test_analyze_then_download_then_serve(client, queue, fake_ytdlp, settings):
    queue.run = True
    r = client.post("/api/media/analyze", json={"url": "https://x.com/janedoe/status/1790000000000000000"})
    job = client.get(f"/api/jobs/{r.json()['id']}").json()
    assert job["status"] == "completed", job
    res = job["result"]
    assert res["caption"].startswith("Sunrise over the bay 🌅\n\n")
    assert res["title_is_generated"] is True
    assert res["thumbnail_file_id"]
    assert client.get(f"/api/media/{res['thumbnail_file_id']}/file").headers["content-type"] == "image/jpeg"

    r = client.post("/api/media/download", json={"analysis_job_id": job["id"], "format_id": "http-832"})
    dl = client.get(f"/api/jobs/{r.json()['id']}").json()
    assert dl["status"] == "completed", dl
    assert fake_ytdlp[-1]["format"].startswith("http-832")
    assert fake_ytdlp[-1]["max_filesize"] == settings.max_filesize_mb * 1024 * 1024
    file_id = dl["result"]["media_file_id"]
    assert dl["result"]["has_audio"] is True and dl["result"]["acodec"] == "aac"

    f = client.get(f"/api/media/{file_id}/file?download=1")
    assert f.status_code == 200 and f.headers["content-type"] == "video/mp4"
    assert "attachment" in f.headers["content-disposition"] and f.content[4:8] == b"ftyp"
    partial = client.get(f"/api/media/{file_id}/file", headers={"Range": "bytes=0-99"})
    assert partial.status_code == 206 and len(partial.content) == 100

    src = client.get(f"/api/media/{file_id}").json()["source"]
    assert src["caption"] == res["caption"] and src["hashtags"] == ["#sunrise", "#Café", "#日本"]

    hist = client.get("/api/media/history").json()["items"]
    assert hist[0]["status"] == "completed" and hist[0]["file"]["id"] == file_id
    assert hist[0]["title"].startswith("Jane Doe")

    assert client.delete(f"/api/media/{file_id}").json()["deleted"] == [file_id]
    assert client.get(f"/api/media/{file_id}/file").status_code == 410
    assert client.get("/api/media/history").json()["items"][0]["file"]["available"] is False


@needs_ffmpeg
def test_download_failure_is_reported_clearly(client, queue, fake_ytdlp, monkeypatch):
    queue.run = True
    r = client.post("/api/media/analyze", json={"url": "https://x.com/janedoe/status/1"})
    analysis_id = r.json()["id"]

    def fail(request, timeout, on_event=None, settings=None):
        raise MediaError("login_required", "The platform requires a login to view this video.", "ERROR: login")

    monkeypatch.setattr(tasks, "run_ytdlp", fail)
    r = client.post("/api/media/download", json={"analysis_job_id": analysis_id, "format_id": "best"})
    job = client.get(f"/api/jobs/{r.json()['id']}").json()
    assert job["status"] == "failed"
    assert job["error"] == {"code": "login_required", "message": "The platform requires a login to view this video."}
    assert job["error_detail"] == "ERROR: login"  # admins see the technical detail
    hist = client.get("/api/media/history").json()["items"][0]
    assert hist["status"] == "failed" and "login" in hist["error_message"]


def test_rejected_redirect_fails_job(client, queue, monkeypatch):
    from app.security.url_guard import URLRejected

    def reject(url, s=None):
        raise URLRejected("blocked_address", "Blocked for security.")

    monkeypatch.setattr(tasks, "resolve_redirects", reject)
    queue.run = True
    r = client.post("/api/media/analyze", json={"url": "https://t.co/abc"})
    job = client.get(f"/api/jobs/{r.json()['id']}").json()
    assert job["status"] == "failed" and job["error"]["code"] == "blocked_address"


def test_unexpected_exception_marks_failed_and_cleans_workdir(client, queue, monkeypatch, settings):
    def crash(request, timeout, on_event=None, settings=None):
        from pathlib import Path

        Path(request["workdir"]).mkdir(parents=True, exist_ok=True)
        raise RuntimeError("kaboom")

    monkeypatch.setattr(tasks, "run_ytdlp", crash)
    monkeypatch.setattr(tasks, "resolve_redirects", lambda url, s=None: url)
    queue.run = True
    r = client.post("/api/media/analyze", json={"url": "https://x.com/a/status/1"})
    job = client.get(f"/api/jobs/{r.json()['id']}").json()
    assert job["status"] == "failed" and job["error"]["code"] == "internal_error"
    assert list(settings.work_dir.iterdir()) == []


def test_storage_quota_blocks_new_downloads(client, admin, settings):
    from tests.test_jobs_api import _completed_analysis

    settings.max_storage_mb = 1
    (settings.media_dir / "big.bin").write_bytes(b"\0" * (1024 * 1024 + 1))
    analysis_id = _completed_analysis(admin)
    r = client.post("/api/media/download", json={"analysis_job_id": analysis_id, "format_id": "best"})
    assert r.status_code == 507 and r.json()["detail"]["code"] == "storage_full"


def test_error_classification():
    from app.media.errors import classify_error

    cases = {
        "ERROR: [Instagram] abc: Requested content is not available, rate-limit reached or login required": "login_required",
        "ERROR: [youtube] x: Sign in to confirm your age. This video may be inappropriate for some users.": "login_required",
        "ERROR: [generic] Unsupported URL: https://example.com": "unsupported_url",
        "ERROR: This video is DRM protected": "drm_protected",
        "ERROR: [twitter] 1: HTTP Error 404: Not Found": "not_found",
        "ERROR: HTTP Error 429: Too Many Requests": "rate_limited",
        "BlockedConnectionError: Blocked connection to non-public address 10.0.0.1": "blocked_address",
        "SizeLimitExceeded: File is larger than max-filesize": "too_large",
        "something odd": "download_failed",
    }
    for raw, code in cases.items():
        assert classify_error(raw).code == code, raw
