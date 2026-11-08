import os
import time
from datetime import timedelta

from app.db import session_scope
from app.jobs.cleanup import cleanup_expired
from app.models import FileKind, JobKind, JobStatus, MediaFile, MediaJob, utcnow


def _file(settings, admin, rel, kind=FileKind.VIDEO, expires_in=None):
    root = settings.watermark_dir if kind == FileKind.WATERMARK else settings.media_dir
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"data")
    with session_scope() as db:
        mf = MediaFile(user_id=admin, kind=kind, path=rel, filename=p.name, mime_type="video/mp4", size_bytes=4,
                       expires_at=(utcnow() + expires_in) if expires_in is not None else None)
        db.add(mf)
        db.flush()
        return mf.id, p


def test_expired_files_removed_fresh_files_kept(app, admin, settings):
    old_id, old_path = _file(settings, admin, "j1/video.mp4", expires_in=timedelta(minutes=-1))
    new_id, new_path = _file(settings, admin, "j2/video.mp4", expires_in=timedelta(minutes=30))
    wm_id, wm_path = _file(settings, admin, "w.png", kind=FileKind.WATERMARK)
    stats = cleanup_expired(settings)
    assert stats["files_deleted"] == 1
    assert not old_path.exists() and not old_path.parent.exists()
    assert new_path.exists() and wm_path.exists()
    with session_scope() as db:
        assert db.get(MediaFile, old_id).deleted_at is not None
        assert db.get(MediaFile, new_id).deleted_at is None


def test_default_retention_is_60_minutes(settings):
    assert settings.retention_minutes == 60


def test_stale_work_dirs_and_jobs(app, admin, settings):
    stale = settings.work_dir / "deadjob"
    stale.mkdir()
    (stale / "partial.part").write_bytes(b"x")
    old = time.time() - 10 * 3600
    os.utime(stale, (old, old))
    fresh = settings.work_dir / "livejob"
    fresh.mkdir()
    with session_scope() as db:
        job = MediaJob(user_id=admin, kind=JobKind.DOWNLOAD, status=JobStatus.DOWNLOADING)
        db.add(job)
        db.flush()
        job.updated_at = utcnow() - timedelta(hours=10)
        jid = job.id
    with session_scope() as db:
        db.query(MediaJob).filter_by(id=jid).update({"updated_at": utcnow() - timedelta(hours=10)})
    stats = cleanup_expired(settings)
    assert not stale.exists() and fresh.exists()
    assert stats["stale_jobs_failed"] == 1
    with session_scope() as db:
        assert db.get(MediaJob, jid).status == JobStatus.FAILED


def test_orphan_media_dirs_removed_after_retention(app, admin, settings):
    orphan = settings.media_dir / "orphan"
    orphan.mkdir()
    (orphan / "x.mp4").write_bytes(b"x")
    old = time.time() - 2 * 3600
    os.utime(orphan, (old, old))
    cleanup_expired(settings)
    assert not orphan.exists()
