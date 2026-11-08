"""Background tasks executed by the worker: analyze, download, process."""
from __future__ import annotations

import logging
import shutil
import time
import traceback
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select

from ..config import get_settings
from ..db import session_scope
from ..media.errors import JobCancelled, MediaError
from ..media.ffmpeg import FFmpeg
from ..media.formats import selector_for
from ..media.storage import (check_disk_capacity, match_parent_group, mime_for, remove_tree, resolve_stored,
                             safe_filename)
from ..media.ytdlp import run_ytdlp
from ..models import DownloadHistory, FileKind, JobKind, JobStatus, MediaFile, MediaJob, utcnow
from ..security.url_guard import URLRejected, resolve_redirects, validate_url

log = logging.getLogger(__name__)


def _update(job_id: str, **fields: Any) -> None:
    with session_scope() as db:
        job = db.get(MediaJob, job_id)
        if job is not None:
            for k, v in fields.items():
                setattr(job, k, v)


def _fail(job_id: str, code: str, message: str, detail: str | None = None) -> None:
    log.warning("job %s failed: %s %s", job_id, code, message)
    with session_scope() as db:
        job = db.get(MediaJob, job_id)
        if job is None:
            return
        job.status = JobStatus.FAILED
        job.error_code = code
        job.error_message = message
        job.error_detail = (detail or "")[-8000:] or None
        job.finished_at = utcnow()
        job.stage = "Cancelled" if code == "cancelled" else "Failed"
        if job.kind in (JobKind.DOWNLOAD, JobKind.PROCESS) and code != "cancelled":
            parent = db.get(MediaJob, job.parent_job_id) if job.parent_job_id else None
            db.add(DownloadHistory(
                user_id=job.user_id, job_id=job.id, kind=job.kind, status="failed",
                source_url=job.source_url, platform=job.platform,
                title=((parent.result or {}).get("title") if parent else None) or (job.options or {}).get("title"),
                format_label=((job.options or {}).get("format") or {}).get("label"),
                error_message=message,
            ))


def _expiry(minutes: int | None = None):
    return utcnow() + timedelta(minutes=minutes or get_settings().retention_minutes)


def _check_cancel(job_id: str) -> None:
    with session_scope() as db:
        job = db.get(MediaJob, job_id)
        if job is not None and job.cancel_requested:
            raise JobCancelled()


def run_job(job_id: str) -> None:
    with session_scope() as db:
        job = db.get(MediaJob, job_id)
        if job is None:
            log.error("job %s not found", job_id)
            return
        if job.status != JobStatus.QUEUED:
            log.info("job %s already %s; skipping", job_id, job.status)
            return
        kind = job.kind
    handler = {JobKind.ANALYZE: _analyze, JobKind.DOWNLOAD: _download, JobKind.PROCESS: _process}.get(kind)
    workdir = get_settings().work_dir / job_id
    try:
        if handler is None:
            raise MediaError("invalid_job", f"Unknown job kind {kind}")
        handler(job_id, workdir)
    except URLRejected as exc:
        _fail(job_id, exc.code, exc.message)
    except MediaError as exc:
        _fail(job_id, exc.code, exc.message, exc.detail)
    except Exception as exc:  # noqa: BLE001
        _fail(job_id, "internal_error", f"Unexpected server error ({type(exc).__name__}).", traceback.format_exc())
    finally:
        remove_tree(workdir, get_settings().work_dir)


def on_rq_failure(job, connection, exc_type, exc_value, tb) -> None:
    """Called by RQ if the worker itself dies or the hard timeout fires."""
    job_id = (job.args or [None])[0]
    if not job_id:
        return
    with session_scope() as db:
        mj = db.get(MediaJob, job_id)
        active = mj is not None and mj.status in JobStatus.ACTIVE
    if active:
        _fail(job_id, "worker_error", "The background worker stopped while running this job.", f"{exc_type}: {exc_value}")


# ------------------------------------------------------------------ analyze
def _analyze(job_id: str, workdir: Path) -> None:
    s = get_settings()
    with session_scope() as db:
        job = db.get(MediaJob, job_id)
        source_url, user_id = job.source_url, job.user_id
        retention = (job.options or {}).get("retention_minutes")
    _update(job_id, status=JobStatus.ANALYZING, started_at=utcnow(), stage="Checking link", progress=0.05)
    url = resolve_redirects(validate_url(source_url, s), s)
    _update(job_id, resolved_url=url, stage="Reading video details", progress=0.2)

    res = run_ytdlp({"mode": "analyze", "url": url, "workdir": str(workdir)}, timeout=s.analyze_timeout_seconds)
    summary: dict = res["summary"]
    summary["too_long"] = bool(summary.get("duration") and summary["duration"] > s.max_duration_seconds)
    summary["max_duration_seconds"] = s.max_duration_seconds
    if not [f for f in summary.get("formats", []) if f["format_id"] != "best"] and not summary.get("duration"):
        raise MediaError("no_video", "No downloadable video was found in this post.")

    thumb_src = res.get("thumbnail")
    if thumb_src and Path(thumb_src).is_file():
        out_dir = s.media_dir / job_id
        out_dir.mkdir(parents=True, exist_ok=True)
        ext = Path(thumb_src).suffix.lower() or ".jpg"
        dst = out_dir / f"thumbnail{ext}"
        shutil.move(thumb_src, dst)
        match_parent_group(dst)
        with session_scope() as db:
            mf = MediaFile(
                user_id=user_id, job_id=job_id, kind=FileKind.THUMBNAIL, path=f"{job_id}/{dst.name}",
                filename=f"thumbnail{ext}", mime_type=mime_for(dst), size_bytes=dst.stat().st_size,
                expires_at=_expiry(retention),
            )
            db.add(mf)
            db.flush()
            summary["thumbnail_file_id"] = mf.id
    summary["warnings"] = res.get("warnings", [])[:10]
    _update(job_id, status=JobStatus.COMPLETED, progress=1.0, stage="Ready", result=summary,
            platform=summary.get("platform"), finished_at=utcnow())


# ------------------------------------------------------------------ download
def _download(job_id: str, workdir: Path) -> None:
    s = get_settings()
    with session_scope() as db:
        job = db.get(MediaJob, job_id)
        parent = db.get(MediaJob, job.parent_job_id)
        option = (job.options or {})["format"]
        job_limits = (job.options or {}).get("limits") or {}
        retention = (job.options or {}).get("retention_minutes")
        url = job.source_url
        user_id = job.user_id
        title = (parent.result or {}).get("title") if parent else None
        caption = (parent.result or {}).get("caption") if parent else None
        platform = job.platform

    check_disk_capacity(s)
    _update(job_id, status=JobStatus.DOWNLOADING, started_at=utcnow(), stage="Starting download", progress=0.02)

    expected_streams = 2 if (option.get("needs_merge") or option["format_id"] == "best") else 1
    last = {"t": 0.0, "overall": 0.0}

    max_mb = int(job_limits.get("max_filesize_mb") or s.max_filesize_mb)
    max_duration = int(job_limits.get("max_duration_seconds") or s.max_duration_seconds)

    def on_event(msg: dict) -> None:
        now = time.monotonic()
        if now - last.get("cancel_check", 0.0) >= 1.0:
            last["cancel_check"] = now
            _check_cancel(job_id)
        if msg.get("type") == "postprocess":
            _update(job_id, stage="Merging audio and video", progress=0.85)
            return
        if msg.get("type") != "progress" or now - last["t"] < 1.0:
            return
        last["t"] = now
        stream = int(msg.get("stream") or 0)
        frac = 0.0
        if msg.get("total"):
            frac = min(1.0, (msg.get("downloaded") or 0) / msg["total"])
        overall = min(0.99, (stream + frac) / max(expected_streams, stream + 1))
        overall = last["overall"] = max(last["overall"], overall)  # never move backwards
        mb = (msg.get("downloaded") or 0) / 1_048_576
        _update(job_id, progress=round(0.02 + 0.8 * overall, 3), stage=f"Downloading ({mb:.1f} MB)")

    res = run_ytdlp(
        {
            "mode": "download", "url": url, "workdir": str(workdir), "format": selector_for(option),
            "max_filesize": max_mb * 1024 * 1024, "max_duration": max_duration,
        },
        timeout=s.download_timeout_seconds, on_event=on_event,
    )
    _update(job_id, status=JobStatus.PROCESSING, stage="Preparing MP4", progress=0.9)
    src = Path(res["filepath"])
    out_dir = s.media_dir / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / "video.mp4"
    probe = FFmpeg(s).ensure_mp4(src, dst, timeout=s.process_timeout_seconds)
    if probe.size > max_mb * 1024 * 1024:
        dst.unlink(missing_ok=True)
        raise MediaError("too_large", "The video is larger than the configured size limit.")
    w, h = probe.display_size
    filename = safe_filename(title, f"video_{job_id[:8]}", "mp4")
    with session_scope() as db:
        mf = MediaFile(
            user_id=user_id, job_id=job_id, kind=FileKind.VIDEO, path=f"{job_id}/video.mp4", filename=filename,
            mime_type="video/mp4", size_bytes=dst.stat().st_size, width=w, height=h, duration=probe.duration,
            vcodec=probe.vcodec, acodec=probe.acodec, expires_at=_expiry(retention),
        )
        db.add(mf)
        db.flush()
        db.add(DownloadHistory(
            user_id=user_id, job_id=job_id, media_file_id=mf.id, kind="download", status="completed",
            source_url=url, platform=platform, title=title, format_label=option.get("label"),
            size_bytes=mf.size_bytes,
        ))
        job = db.get(MediaJob, job_id)
        job.status = JobStatus.COMPLETED
        job.progress = 1.0
        job.stage = "Completed"
        job.finished_at = utcnow()
        job.result = {
            "media_file_id": mf.id, "filename": filename, "size_bytes": mf.size_bytes, "width": w, "height": h,
            "duration": probe.duration, "vcodec": probe.vcodec, "acodec": probe.acodec, "title": title,
            "caption": caption, "expires_at": mf.expires_at.isoformat(), "has_audio": probe.acodec is not None,
        }


# ------------------------------------------------------------------ process
def _process(job_id: str, workdir: Path) -> None:
    s = get_settings()
    ff = FFmpeg(s)
    with session_scope() as db:
        job = db.get(MediaJob, job_id)
        opts = dict(job.options or {})
        retention = opts.get("retention_minutes")
        user_id = job.user_id
        src_file = db.get(MediaFile, job.input_file_id)
        if src_file is None or not src_file.available:
            raise MediaError("file_missing", "The source video has expired or was deleted. Download it again.")
        src = resolve_stored(s.media_dir, src_file.path)
        src_name = Path(src_file.filename).stem
        watermark = None
        if opts.get("watermark_file_id"):
            wm = db.get(MediaFile, opts["watermark_file_id"])
            if wm is None or wm.deleted_at is not None or wm.kind != FileKind.WATERMARK:
                raise MediaError("watermark_missing", "The selected watermark image no longer exists.")
            watermark = resolve_stored(s.watermark_dir, wm.path)

    check_disk_capacity(s)
    _update(job_id, status=JobStatus.PROCESSING, started_at=utcnow(), stage="Processing video", progress=0.1)
    out_dir = s.media_dir / job_id
    out_dir.mkdir(parents=True, exist_ok=True)

    result: dict[str, Any] = {"media_file_id": None, "thumbnail_file_ids": []}
    output_id: str | None = None
    thumb_source = src
    thumb_duration = None
    needs_video = bool(watermark) or opts.get("aspect", "original") != "original"
    if needs_video:
        dst = out_dir / "processed.mp4"
        probe = ff.process(
            src, dst, aspect=opts.get("aspect", "original"), fill_mode=opts.get("fill_mode", "blur"),
            watermark=watermark, watermark_size_pct=float(opts.get("watermark_size_pct", 15)),
            watermark_opacity=float(opts.get("watermark_opacity", 0.8)),
            watermark_margin_pct=float(opts.get("watermark_margin_pct", 3)), timeout=s.process_timeout_seconds,
        )
        w, h = probe.display_size
        with session_scope() as db:
            mf = MediaFile(
                user_id=user_id, job_id=job_id, parent_file_id=src_file.id, kind=FileKind.PROCESSED,
                path=f"{job_id}/processed.mp4", filename=f"{src_name}_processed.mp4", mime_type="video/mp4",
                size_bytes=dst.stat().st_size, width=w, height=h, duration=probe.duration, vcodec=probe.vcodec,
                acodec=probe.acodec, expires_at=_expiry(retention),
            )
            db.add(mf)
            db.flush()
            output_id = mf.id
        result.update({"media_file_id": output_id, "width": w, "height": h, "duration": probe.duration,
                       "has_audio": probe.acodec is not None})
        thumb_source, thumb_duration = dst, probe.duration
        _update(job_id, progress=0.8, stage="Generating thumbnails" if opts.get("thumbnails") else "Finishing")

    if opts.get("thumbnails"):
        if thumb_duration is None:
            thumb_duration = ff.probe(thumb_source).duration
        thumbs = ff.thumbnails(thumb_source, out_dir / "thumbs", thumb_duration, count=3)
        with session_scope() as db:
            for i, t in enumerate(thumbs, 1):
                tf = MediaFile(
                    user_id=user_id, job_id=job_id, parent_file_id=output_id or src_file.id,
                    kind=FileKind.THUMBNAIL, path=f"{job_id}/thumbs/{t.name}", filename=f"{src_name}_thumb_{i}.jpg",
                    mime_type="image/jpeg", size_bytes=t.stat().st_size, expires_at=_expiry(retention),
                )
                db.add(tf)
                db.flush()
                result["thumbnail_file_ids"].append(tf.id)

    with session_scope() as db:
        job = db.get(MediaJob, job_id)
        if output_id:
            out = db.get(MediaFile, output_id)
            db.add(DownloadHistory(
                user_id=user_id, job_id=job_id, media_file_id=output_id, kind="process", status="completed",
                source_url=job.source_url, platform=job.platform, title=f"{src_name} (processed)",
                format_label=_describe(opts), size_bytes=out.size_bytes,
            ))
        job.status = JobStatus.COMPLETED
        job.progress = 1.0
        job.stage = "Completed"
        job.finished_at = utcnow()
        job.result = result


def _describe(opts: dict) -> str:
    bits = []
    if opts.get("aspect") == "9:16":
        bits.append(f"9:16 ({opts.get('fill_mode', 'blur')})")
    if opts.get("watermark_file_id"):
        bits.append("watermark")
    if opts.get("thumbnails"):
        bits.append("thumbnails")
    return ", ".join(bits) or "processed"


def find_active_jobs(db, user_id: int) -> int:
    return len(db.scalars(select(MediaJob.id).where(
        MediaJob.user_id == user_id, MediaJob.status.in_(JobStatus.ACTIVE))).all())
