from app.db import session_scope
from app.models import JobKind, JobStatus, MediaJob, User
from app.security.passwords import hash_password
from tests.test_formats import load


def _completed_analysis(user_id: int, **extra) -> str:
    from app.media.formats import summarize_info

    summary = {**summarize_info(load("youtube_short.json")), "too_long": False, **extra}
    with session_scope() as db:
        job = MediaJob(user_id=user_id, kind=JobKind.ANALYZE, status=JobStatus.COMPLETED,
                       source_url="https://www.youtube.com/shorts/abcdefghijk", result=summary, platform="youtube")
        db.add(job)
        db.flush()
        return job.id


def test_analyze_creates_queued_job(client, queue):
    r = client.post("/api/media/analyze", json={"url": "youtube.com/shorts/abcdefghijk"})
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["status"] == "queued" and job["kind"] == "analyze"
    assert job["source_url"] == "https://youtube.com/shorts/abcdefghijk"
    assert queue.enqueued == [job["id"]]
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "queued"


def test_invalid_url_creates_no_job(client, queue):
    r = client.post("/api/media/analyze", json={"url": "http://169.254.169.254/latest/meta-data"})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "ip_literal"
    assert queue.enqueued == []


def test_pending_job_limit(client, settings):
    settings.max_pending_jobs_per_user = 2
    codes = [client.post("/api/media/analyze", json={"url": "https://x.com/a/status/1"}).status_code for _ in range(3)]
    assert codes == [202, 202, 429]


def test_queue_outage_is_reported(client, queue):
    def boom(job_id, timeout):
        raise ConnectionError("redis down")

    queue.enqueue = boom
    r = client.post("/api/media/analyze", json={"url": "https://x.com/a/status/1"})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "queue_unavailable"
    jobs = client.get("/api/jobs").json()["items"]
    assert jobs[0]["status"] == "failed"


def test_download_job_creation(client, admin, queue):
    analysis_id = _completed_analysis(admin)
    r = client.post("/api/media/download", json={"analysis_job_id": analysis_id, "format_id": "137"})
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["kind"] == "download" and job["parent_job_id"] == analysis_id
    assert job["options"]["format"]["format_id"] == "137"
    assert queue.enqueued[-1] == job["id"]


def test_download_rejects_unknown_format(client, admin):
    analysis_id = _completed_analysis(admin)
    r = client.post("/api/media/download", json={"analysis_job_id": analysis_id, "format_id": "bv*+ba; rm -rf /"})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "invalid_format"


def test_download_rejects_too_long_video(client, admin):
    analysis_id = _completed_analysis(admin, too_long=True, max_duration_seconds=60)
    r = client.post("/api/media/download", json={"analysis_job_id": analysis_id, "format_id": "best"})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "too_long"


def test_download_requires_finished_analysis(client, admin):
    with session_scope() as db:
        job = MediaJob(user_id=admin, kind=JobKind.ANALYZE, status=JobStatus.ANALYZING, source_url="https://x.com/a")
        db.add(job)
        db.flush()
        jid = job.id
    r = client.post("/api/media/download", json={"analysis_job_id": jid, "format_id": "best"})
    assert r.status_code == 409


def test_users_cannot_see_each_others_jobs(client, admin):
    with session_scope() as db:
        other = User(username="other", password_hash=hash_password("Another-Password-1"), role="admin")
        db.add(other)
        db.flush()
        other_id = other.id
    other_job = _completed_analysis(other_id)
    assert client.get(f"/api/jobs/{other_job}").status_code == 404
    r = client.post("/api/media/download", json={"analysis_job_id": other_job, "format_id": "best"})
    assert r.status_code == 404


def test_job_list_filters(client):
    client.post("/api/media/analyze", json={"url": "https://x.com/a/status/1"})
    assert len(client.get("/api/jobs?status=active").json()["items"]) == 1
    assert client.get("/api/jobs?status=completed").json()["items"] == []
    assert client.get("/api/jobs?status=bogus").status_code == 400
