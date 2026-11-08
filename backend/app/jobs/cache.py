"""Share recent results between visitors.

When someone analyzes or downloads a video that another visitor fetched in the last few
minutes, the stored result is reused: instant for the visitor, and one less request
from the server's IP to the platform (which helps avoid rate limits and blocks).
Files are hard-linked, so a shared download costs no extra disk space, and each copy
still expires on its own owner's schedule.
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..media.storage import link_or_copy, resolve_stored
from ..models import DownloadHistory, FileKind, JobKind, JobStatus, MediaFile, MediaJob, new_id, utcnow

# Share/tracking parameters that don't change which video a link points to.
_TRACKING = {
    "si", "igsh", "igshid", "feature", "ref", "ref_src", "ref_url", "s", "t", "share_id", "sh", "mibextid",
    "rdid", "_r", "_t", "is_from_webapp", "sender_device", "web_id", "fbclid", "gclid", "context", "pp",
}


def cache_key(url: str | None) -> str | None:
    if not url:
        return None
    p = urlsplit(url)
    host = (p.hostname or "").lower()
    for prefix in ("www.", "m.", "mobile.", "old.", "new."):
        if host.startswith(prefix):
            host = host[len(prefix):]
            break
    host = {"twitter.com": "x.com"}.get(host, host)
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if k.lower() not in _TRACKING and not k.lower().startswith("utm_")]
    return urlunsplit(("https", host, p.path.rstrip("/") or "/", urlencode(sorted(query)), ""))


def _expiry(minutes: int):
    return utcnow() + timedelta(minutes=minutes)


def find_cached_analysis(db: Session, url: str) -> MediaJob | None:
    s = get_settings()
    if s.result_cache_minutes <= 0:
        return None
    key = cache_key(url)
    since = utcnow() - timedelta(minutes=s.result_cache_minutes)
    for job in db.scalars(select(MediaJob).where(
            MediaJob.kind == JobKind.ANALYZE, MediaJob.status == JobStatus.COMPLETED,
            MediaJob.finished_at >= since).order_by(MediaJob.finished_at.desc()).limit(300)):
        if job.result and key in (cache_key(job.source_url), cache_key(job.resolved_url)):
            return job
    return None


def clone_analysis(db: Session, src: MediaJob, user_id: int, url: str, options: dict) -> MediaJob:
    s = get_settings()
    now = utcnow()
    job = MediaJob(id=new_id(), user_id=user_id, kind=JobKind.ANALYZE, status=JobStatus.COMPLETED,
                   progress=1.0, stage="Ready", source_url=url, resolved_url=src.resolved_url,
                   platform=src.platform, options={**options, "cached_from": src.id},
                   started_at=now, finished_at=now)
    result = dict(src.result or {})
    result["cached"] = True
    thumb_id = result.pop("thumbnail_file_id", None)
    thumb = db.get(MediaFile, thumb_id) if thumb_id else None
    if thumb is not None and thumb.available:
        try:
            src_path = resolve_stored(s.media_dir, thumb.path)
            if src_path.is_file():
                rel = f"{job.id}/{Path(thumb.path).name}"
                link_or_copy(src_path, s.media_dir / rel)
                tf = MediaFile(user_id=user_id, job_id=job.id, kind=FileKind.THUMBNAIL, path=rel,
                               filename=thumb.filename, mime_type=thumb.mime_type, size_bytes=thumb.size_bytes,
                               expires_at=_expiry(options.get("retention_minutes", s.retention_minutes)))
                db.add(job)
                db.flush()
                db.add(tf)
                db.flush()
                result["thumbnail_file_id"] = tf.id
        except OSError:
            pass
    job.result = result
    db.add(job)
    db.commit()
    return job


def find_cached_download(db: Session, analysis: MediaJob, format_id: str, max_bytes: int) -> MediaFile | None:
    s = get_settings()
    if not s.reuse_downloads:
        return None
    key = cache_key(analysis.resolved_url or analysis.source_url)
    since = utcnow() - timedelta(minutes=max(s.retention_minutes, s.admin_retention_minutes))
    min_left = utcnow() + timedelta(minutes=5)
    for job in db.scalars(select(MediaJob).where(
            MediaJob.kind == JobKind.DOWNLOAD, MediaJob.status == JobStatus.COMPLETED,
            MediaJob.finished_at >= since).order_by(MediaJob.finished_at.desc()).limit(300)):
        if ((job.options or {}).get("format") or {}).get("format_id") != format_id:
            continue
        if cache_key(job.source_url) != key or not job.result:
            continue
        mf = db.get(MediaFile, job.result.get("media_file_id"))
        if (mf is None or mf.deleted_at is not None or mf.size_bytes > max_bytes
                or (mf.expires_at is not None and mf.expires_at < min_left)):
            continue
        try:
            if resolve_stored(s.media_dir, mf.path).is_file():
                return mf
        except OSError:
            continue
    return None


def clone_download(db: Session, cached: MediaFile, analysis: MediaJob, user_id: int, options: dict) -> MediaJob:
    s = get_settings()
    now = utcnow()
    job = MediaJob(id=new_id(), user_id=user_id, kind=JobKind.DOWNLOAD, status=JobStatus.COMPLETED,
                   progress=1.0, stage="Completed", parent_job_id=analysis.id,
                   source_url=analysis.resolved_url or analysis.source_url, platform=analysis.platform,
                   options={**options, "cached_from_file": cached.id}, started_at=now, finished_at=now)
    db.add(job)
    db.flush()
    rel = f"{job.id}/video.mp4"
    link_or_copy(resolve_stored(s.media_dir, cached.path), s.media_dir / rel)
    mf = MediaFile(user_id=user_id, job_id=job.id, kind=FileKind.VIDEO, path=rel, filename=cached.filename,
                   mime_type=cached.mime_type, size_bytes=cached.size_bytes, width=cached.width,
                   height=cached.height, duration=cached.duration, vcodec=cached.vcodec, acodec=cached.acodec,
                   expires_at=_expiry(options.get("retention_minutes", s.retention_minutes)))
    db.add(mf)
    db.flush()
    title = (analysis.result or {}).get("title")
    db.add(DownloadHistory(user_id=user_id, job_id=job.id, media_file_id=mf.id, kind="download",
                           status="completed", source_url=job.source_url, platform=job.platform, title=title,
                           format_label=(options.get("format") or {}).get("label"), size_bytes=mf.size_bytes))
    job.result = {
        "media_file_id": mf.id, "filename": mf.filename, "size_bytes": mf.size_bytes, "width": mf.width,
        "height": mf.height, "duration": mf.duration, "vcodec": mf.vcodec, "acodec": mf.acodec, "title": title,
        "caption": (analysis.result or {}).get("caption"), "expires_at": mf.expires_at.isoformat(),
        "has_audio": mf.acodec is not None, "cached": True,
    }
    db.commit()
    return job
