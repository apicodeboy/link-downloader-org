"""Retention cleanup: removes expired media, stale work directories and stuck jobs.

Run every few minutes by the `video-downloader-cleanup.timer` systemd timer
(`python -m app.cli cleanup`). Safe to run any time.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import session_scope
from ..media.storage import remove_tree, resolve_stored
from ..models import FileKind, JobStatus, MediaFile, MediaJob, utcnow
from ..security.sessions import purge_expired

log = logging.getLogger(__name__)


def file_root(kind: str, settings: Settings | None = None) -> Path:
    s = settings or get_settings()
    return s.watermark_dir if kind == FileKind.WATERMARK else s.media_dir


def delete_media_file(db: Session, mf: MediaFile, settings: Settings | None = None) -> None:
    """Delete a file from disk and mark its row deleted (history rows are kept)."""
    try:
        path = resolve_stored(file_root(mf.kind, settings), mf.path)
        path.unlink(missing_ok=True)
        parent = path.parent
        root = file_root(mf.kind, settings)
        while parent != root and root in parent.parents and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
    except OSError as exc:
        log.warning("could not delete %s: %s", mf.path, exc)
    mf.deleted_at = utcnow()


def cleanup_expired(settings: Settings | None = None) -> dict[str, int]:
    s = settings or get_settings()
    s.ensure_dirs()
    now = utcnow()
    stats = {"files_deleted": 0, "work_dirs_removed": 0, "stale_jobs_failed": 0, "sessions_purged": 0}

    with session_scope() as db:
        expired = db.scalars(select(MediaFile).where(
            MediaFile.deleted_at.is_(None), MediaFile.expires_at.is_not(None), MediaFile.expires_at <= now)).all()
        for mf in expired:
            delete_media_file(db, mf, s)
            stats["files_deleted"] += 1

        longest = max(s.download_timeout_seconds, s.process_timeout_seconds, s.analyze_timeout_seconds)
        stale_before = now - timedelta(seconds=longest * 2 + 600)
        for job in db.scalars(select(MediaJob).where(
                MediaJob.status.in_(JobStatus.ACTIVE), MediaJob.updated_at < stale_before)).all():
            job.status = JobStatus.FAILED
            job.error_code = "stale"
            job.error_message = "The job stopped responding and was marked failed."
            job.finished_at = now
            stats["stale_jobs_failed"] += 1
        stats["sessions_purged"] = purge_expired(db)

    # Work directories left behind by crashed jobs.
    cutoff = time.time() - max(s.download_timeout_seconds, s.process_timeout_seconds) * 2
    for entry in s.work_dir.iterdir():
        try:
            if entry.is_dir() and entry.stat().st_mtime < cutoff:
                remove_tree(entry, s.work_dir)
                stats["work_dirs_removed"] += 1
        except OSError:
            pass
    # Media directories with no tracked live files and older than the retention period.
    retention_cutoff = time.time() - s.retention_minutes * 60
    with session_scope() as db:
        live_dirs = {p.split("/", 1)[0] for p in db.scalars(select(MediaFile.path).where(
            MediaFile.deleted_at.is_(None), MediaFile.kind != FileKind.WATERMARK)).all()}
    for entry in s.media_dir.iterdir():
        try:
            if entry.is_dir() and entry.name not in live_dirs and entry.stat().st_mtime < retention_cutoff:
                remove_tree(entry, s.media_dir)
                stats["work_dirs_removed"] += 1
        except OSError:
            pass
    if any(stats.values()):
        log.info("cleanup: %s", stats)
    return stats


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    print(cleanup_expired())
    os._exit(0)
