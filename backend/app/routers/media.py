"""Analyze, download, history, file serving, deletion, and processing endpoints."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import get_settings
from ..db import get_db
from ..deps import api_error, current_user, rate_limited, require_csrf
from ..jobs.cleanup import delete_media_file, file_root
from ..jobs.cache import clone_analysis, clone_download, find_cached_analysis, find_cached_download
from ..jobs.tasks import find_active_jobs
from ..limits import Limits, limits_for
from ..media.errors import MediaError
from ..media.storage import check_disk_capacity, resolve_stored
from ..models import (DownloadHistory, FileKind, JobKind, JobStatus, MediaFile, MediaJob, ProcessingPreset,
                      User)
from ..schemas import AnalyzeIn, DownloadIn, ProcessIn
from ..security.url_guard import URLRejected, validate_url
from ..serializers import file_out, history_out, job_out, personalize

router = APIRouter(prefix="/api/media", tags=["media"],
                   dependencies=[Depends(rate_limited("api", "rate_limit_per_minute"))])


def _check_pending(db: Session, user: User, limits: Limits) -> None:
    s = get_settings()
    total = db.scalar(select(func.count()).select_from(MediaJob).where(MediaJob.status.in_(JobStatus.ACTIVE)))
    # The site owner is never turned away because guests filled the queue.
    if total >= s.max_active_jobs_total and not limits.priority:
        raise api_error(429, "server_busy", "The server is busy with other jobs. Try again in a few minutes.")
    if find_active_jobs(db, user.id) >= limits.max_pending_jobs:
        raise api_error(429, "too_many_jobs", "You already have the maximum number of jobs running. "
                                              "Wait for one to finish.")


def _base_options(limits: Limits) -> dict:
    return {"retention_minutes": limits.retention_minutes, "priority": limits.priority}


def _enqueue(request: Request, db: Session, job: MediaJob, timeout: int, priority: bool = False) -> None:
    try:
        job.rq_job_id = request.app.state.queue.enqueue(job.id, timeout, priority=priority)
        db.commit()
    except Exception as exc:  # Redis down
        job.status = JobStatus.FAILED
        job.error_code = "queue_unavailable"
        job.error_message = "The job queue is unavailable. Check that Redis and the worker are running."
        job.error_detail = str(exc)[:2000]
        db.commit()
        raise api_error(503, "queue_unavailable", job.error_message) from None


def _get_file(db: Session, user: User, file_id: str) -> MediaFile:
    mf = db.get(MediaFile, file_id)
    if mf is None or mf.user_id != user.id:
        raise api_error(404, "not_found", "File not found.")
    return mf


@router.post("/analyze", status_code=202,
             dependencies=[Depends(rate_limited("analyze", "analyze_rate_limit_per_minute"))])
def analyze(body: AnalyzeIn, request: Request, user: User = Depends(current_user),
            _csrf=Depends(require_csrf), db: Session = Depends(get_db)):
    try:
        url = validate_url(body.url)
    except URLRejected as exc:
        audit(db, request, "analyze", user_id=user.id, success=False, reason=exc.code, url=body.url[:500])
        raise api_error(400, exc.code, exc.message) from None
    limits = limits_for(user.role)
    cached = find_cached_analysis(db, url)
    if cached is not None:
        job = clone_analysis(db, cached, user.id, url, _base_options(limits))
        audit(db, request, "analyze", user_id=user.id, target_type="job", target_id=job.id, url=url, cached=True)
        return personalize(job_out(job), limits)
    _check_pending(db, user, limits)
    job = MediaJob(user_id=user.id, kind=JobKind.ANALYZE, source_url=url, stage="Waiting in queue",
                   options=_base_options(limits))
    db.add(job)
    db.commit()
    _enqueue(request, db, job, get_settings().analyze_timeout_seconds, limits.priority)
    audit(db, request, "analyze", user_id=user.id, target_type="job", target_id=job.id, url=url)
    return job_out(job)


@router.post("/download", status_code=202)
def download(body: DownloadIn, request: Request, user: User = Depends(current_user),
             _csrf=Depends(require_csrf), db: Session = Depends(get_db)):
    analysis = db.get(MediaJob, body.analysis_job_id)
    if analysis is None or analysis.user_id != user.id or analysis.kind != JobKind.ANALYZE:
        raise api_error(404, "not_found", "Analysis not found. Analyze the link first.")
    if analysis.status != JobStatus.COMPLETED or not analysis.result:
        raise api_error(409, "not_ready", "The video hasn't finished analyzing yet.")
    result = analysis.result
    limits = limits_for(user.role)
    if result.get("duration") and result["duration"] > limits.max_duration_seconds:
        raise api_error(400, "too_long", f"This video is longer than the {limits.max_duration_seconds // 60}-minute "
                                         "limit on this site.")
    if result.get("is_live"):
        raise api_error(400, "live_content", "Live streams can't be downloaded while they're live.")
    option = next((f for f in result.get("formats", []) if f["format_id"] == body.format_id), None)
    if option is None:
        raise api_error(400, "invalid_format", "That format isn't available for this video. Pick one from the list.")
    options = {**_base_options(limits), "format": option, "title": result.get("title"),
               "limits": {"max_filesize_mb": limits.max_filesize_mb,
                          "max_duration_seconds": limits.max_duration_seconds}}
    cached_file = find_cached_download(db, analysis, option["format_id"], limits.max_filesize_mb * 1024 * 1024)
    if cached_file is not None:
        job = clone_download(db, cached_file, analysis, user.id, options)
        audit(db, request, "download", user_id=user.id, target_type="job", target_id=job.id,
              format=option["label"], url=job.source_url, cached=True)
        return job_out(job)
    _check_pending(db, user, limits)
    try:
        check_disk_capacity()
    except MediaError as exc:
        raise api_error(507, exc.code, exc.message) from None
    job = MediaJob(
        user_id=user.id, kind=JobKind.DOWNLOAD, parent_job_id=analysis.id,
        source_url=analysis.resolved_url or analysis.source_url, platform=analysis.platform,
        options=options, stage="Waiting in queue",
    )
    db.add(job)
    db.commit()
    _enqueue(request, db, job, get_settings().download_timeout_seconds + get_settings().process_timeout_seconds,
             limits.priority)
    audit(db, request, "download", user_id=user.id, target_type="job", target_id=job.id,
          format=option["label"], url=job.source_url)
    return job_out(job)


@router.get("/history")
def history(user: User = Depends(current_user), db: Session = Depends(get_db),
            limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    rows = db.scalars(select(DownloadHistory).where(DownloadHistory.user_id == user.id)
                      .order_by(DownloadHistory.created_at.desc(), DownloadHistory.id.desc())
                      .offset(offset).limit(limit)).all()
    out = []
    for h in rows:
        mf = db.get(MediaFile, h.media_file_id) if h.media_file_id else None
        thumb_id = None
        if mf is not None:
            if mf.kind == FileKind.PROCESSED:
                # Processed videos use the first thumbnail generated from them, if any.
                t = db.scalar(select(MediaFile).where(MediaFile.parent_file_id == mf.id,
                                                      MediaFile.kind == FileKind.THUMBNAIL)
                              .order_by(MediaFile.path).limit(1))
                thumb_id = t.id if t is not None else None
            else:
                job = db.get(MediaJob, h.job_id)
                parent = db.get(MediaJob, job.parent_job_id) if job and job.parent_job_id else None
                thumb_id = (parent.result or {}).get("thumbnail_file_id") if parent else None
            if thumb_id:
                t = db.get(MediaFile, thumb_id)
                thumb_id = thumb_id if t is not None and t.available else None
        out.append(history_out(h, mf, thumb_id))
    return {"items": out, "limit": limit, "offset": offset}


def _source_analysis(db: Session, mf: MediaFile) -> dict | None:
    """Walk processed -> downloaded -> analysis to find the original extracted metadata."""
    seen = 0
    while mf is not None and seen < 10:
        seen += 1
        job = db.get(MediaJob, mf.job_id) if mf.job_id else None
        if job is None:
            return None
        if job.kind == JobKind.PROCESS:
            mf = db.get(MediaFile, job.input_file_id) if job.input_file_id else None
            continue
        parent = db.get(MediaJob, job.parent_job_id) if job.parent_job_id else None
        return parent.result if parent is not None and parent.kind == JobKind.ANALYZE else None
    return None


@router.get("/{file_id}")
def file_info(file_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    mf = _get_file(db, user, file_id)
    children = db.scalars(select(MediaFile).where(MediaFile.parent_file_id == mf.id,
                                                  MediaFile.deleted_at.is_(None))).all()
    src = _source_analysis(db, mf) or {}
    return {
        **file_out(mf),
        "children": [file_out(c) for c in children if c.available],
        "source": {
            "title": src.get("title"), "caption": src.get("caption"), "caption_source": src.get("caption_source"),
            "hashtags": src.get("hashtags", []), "platform": src.get("platform"),
            "webpage_url": src.get("webpage_url"), "creator": src.get("creator"),
        } if src else None,
    }


@router.get("/{file_id}/file")
def serve_file(file_id: str, request: Request, user: User = Depends(current_user),
               db: Session = Depends(get_db), download: bool = Query(False)):
    s = get_settings()
    mf = _get_file(db, user, file_id)
    if not mf.available:
        raise api_error(410, "expired", "This file has expired and was deleted. Download it again.")
    try:
        path = resolve_stored(file_root(mf.kind), mf.path)
    except MediaError:
        raise api_error(404, "not_found", "File not found.") from None
    if not path.is_file():
        raise api_error(410, "expired", "This file is no longer on the server.")
    if download:
        audit(db, request, "file_download", user_id=user.id, target_type="file", target_id=mf.id)
    disposition = "attachment" if download else "inline"
    headers = {"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"}
    if s.use_x_accel_redirect and mf.kind != FileKind.WATERMARK:
        from urllib.parse import quote

        headers.update({
            "X-Accel-Redirect": f"{s.x_accel_prefix}/{quote(mf.path)}",
            "Content-Disposition": f"{disposition}; filename=\"{mf.filename}\"",
            "Content-Type": mf.mime_type,
        })
        return Response(status_code=200, headers=headers)
    return FileResponse(Path(path), media_type=mf.mime_type, filename=mf.filename,
                        content_disposition_type=disposition, headers=headers)


@router.delete("/{file_id}")
def delete_file(file_id: str, request: Request, user: User = Depends(current_user),
                _csrf=Depends(require_csrf), db: Session = Depends(get_db)):
    mf = _get_file(db, user, file_id)
    deleted = []
    if mf.deleted_at is None:
        delete_media_file(db, mf)
        deleted.append(mf.id)
    for child in db.scalars(select(MediaFile).where(MediaFile.parent_file_id == mf.id,
                                                    MediaFile.kind == FileKind.THUMBNAIL,
                                                    MediaFile.deleted_at.is_(None))).all():
        delete_media_file(db, child)
        deleted.append(child.id)
    db.commit()
    audit(db, request, "file_delete", user_id=user.id, target_type="file", target_id=file_id, deleted=deleted)
    return {"deleted": deleted}


@router.post("/{file_id}/process", status_code=202)
def process(file_id: str, body: ProcessIn, request: Request, user: User = Depends(current_user),
            _csrf=Depends(require_csrf), db: Session = Depends(get_db)):
    mf = _get_file(db, user, file_id)
    if mf.kind not in (FileKind.VIDEO, FileKind.PROCESSED):
        raise api_error(400, "invalid_file", "Only downloaded videos can be processed.")
    if not mf.available:
        raise api_error(410, "expired", "This video has expired. Download it again first.")
    limits = limits_for(user.role)
    if limits.process_max_duration_seconds and (mf.duration or 0) > limits.process_max_duration_seconds:
        raise api_error(400, "too_long_to_process",
                        f"Editing is available for videos up to {limits.process_max_duration_seconds // 60} minutes. "
                        "You can still download this one as is.")
    opts = body.model_dump(exclude={"preset_id"})
    if body.preset_id is not None:
        preset = db.get(ProcessingPreset, body.preset_id)
        if preset is None or preset.user_id != user.id:
            raise api_error(404, "not_found", "Preset not found.")
        opts.update({
            "aspect": preset.aspect, "fill_mode": preset.fill_mode, "watermark_file_id": preset.watermark_file_id,
            "watermark_size_pct": preset.watermark_size_pct, "watermark_opacity": preset.watermark_opacity,
            "watermark_margin_pct": preset.watermark_margin_pct, "thumbnails": preset.generate_thumbnails,
        })
    if opts.get("watermark_file_id"):
        wm = db.get(MediaFile, opts["watermark_file_id"])
        if wm is None or wm.user_id != user.id or wm.kind != FileKind.WATERMARK or wm.deleted_at is not None:
            raise api_error(400, "invalid_watermark", "Choose a watermark image you uploaded.")
    if not (opts.get("watermark_file_id") or opts.get("aspect") != "original" or opts.get("thumbnails")):
        raise api_error(400, "nothing_to_do", "Pick at least one change: watermark, 9:16, or thumbnails.")
    _check_pending(db, user, limits)
    try:
        check_disk_capacity()
    except MediaError as exc:
        raise api_error(507, exc.code, exc.message) from None
    source_job = db.get(MediaJob, mf.job_id) if mf.job_id else None
    opts.update(_base_options(limits))
    job = MediaJob(user_id=user.id, kind=JobKind.PROCESS, input_file_id=mf.id, options=opts,
                   parent_job_id=source_job.id if source_job else None,
                   source_url=source_job.source_url if source_job else None,
                   platform=source_job.platform if source_job else None, stage="Waiting in queue")
    db.add(job)
    db.commit()
    _enqueue(request, db, job, get_settings().process_timeout_seconds * 2, limits.priority)
    audit(db, request, "process", user_id=user.id, target_type="job", target_id=job.id, input=mf.id, options=opts)
    return job_out(job)
