"""Health and status endpoints."""
from __future__ import annotations

import platform
import shutil
from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import current_user, require_admin
from ..media.ffmpeg import FFmpeg
from ..media.storage import dir_size
from ..limits import limits_for
from ..media.ytdlp import ytdlp_version
from ..models import AuditLog, JobStatus, MediaJob, User, UserSession, utcnow

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health(request: Request, db: Session = Depends(get_db)):
    """Public liveness check. Reveals only whether each component works."""
    checks = {"database": False, "queue": False, "ffmpeg": False}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception:
        pass
    checks["queue"] = bool(request.app.state.queue.ping())
    checks["ffmpeg"] = FFmpeg().available()
    return {"status": "ok" if all(checks.values()) else "degraded", "checks": checks}


@router.get("/site")
def site():
    """Public, cacheable facts for the FAQ, Terms and Privacy pages. No identity needed."""
    s = get_settings()
    g = limits_for("guest")
    return {
        "site_name": s.site_name,
        "contact_email": s.contact_email or None,
        "platforms": ["X / Twitter", "Instagram", "Facebook", "TikTok", "YouTube", "Reddit"],
        "guest_limits": {
            "max_filesize_mb": g.max_filesize_mb, "max_duration_seconds": g.max_duration_seconds,
            "process_max_duration_seconds": g.process_max_duration_seconds,
            "retention_minutes": g.retention_minutes, "max_pending_jobs": g.max_pending_jobs,
        },
        "history_days": s.guest_session_days,
        "log_retention_days": s.audit_retention_days,
    }


@router.get("/status")
def status(request: Request, _user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Queue and capacity overview for any visitor. No versions, IPs or other users' data."""
    s = get_settings()
    running = db.scalar(select(func.count()).select_from(MediaJob).where(
        MediaJob.status.in_((JobStatus.ANALYZING, JobStatus.DOWNLOADING, JobStatus.PROCESSING))))
    used = dir_size(s.media_dir) + dir_size(s.work_dir)
    return {
        "queue": {"connected": request.app.state.queue.ping(), "depth": request.app.state.queue.depth()},
        "running": running,
        "storage_used_pct": round(100 * used / max(1, s.max_storage_mb * 1024 * 1024)),
        "limits": {
            "retention_minutes": s.retention_minutes, "max_filesize_mb": s.max_filesize_mb,
            "max_duration_seconds": s.max_duration_seconds, "max_pending_jobs_per_user": s.max_pending_jobs_per_user,
        },
    }


@router.get("/admin/status")
def admin_status(request: Request, _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    s = get_settings()
    counts = dict(db.execute(select(MediaJob.status, func.count()).group_by(MediaJob.status)).all())
    disk = shutil.disk_usage(s.data_dir)
    recent_failures = db.scalars(select(MediaJob).where(MediaJob.status == JobStatus.FAILED)
                                 .order_by(MediaJob.created_at.desc()).limit(10)).all()
    recent_audit = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(20)).all()
    day_ago = utcnow() - timedelta(hours=24)
    completed_24h = dict(db.execute(select(MediaJob.kind, func.count()).where(
        MediaJob.status == JobStatus.COMPLETED, MediaJob.finished_at >= day_ago).group_by(MediaJob.kind)).all())
    failures_24h = db.execute(select(MediaJob.error_code, func.count()).where(
        MediaJob.status == JobStatus.FAILED, MediaJob.finished_at >= day_ago, MediaJob.error_code != "cancelled")
        .group_by(MediaJob.error_code).order_by(func.count().desc()).limit(8)).all()
    cached_24h = db.scalar(select(func.count()).select_from(AuditLog).where(
        AuditLog.created_at >= day_ago, AuditLog.action.in_(("analyze", "download")),
        AuditLog.details["cached"].as_boolean().is_(True)))
    visitors_24h = db.scalar(select(func.count(func.distinct(UserSession.user_id))).where(
        UserSession.last_seen_at >= day_ago))
    return {
        "versions": {"yt_dlp": ytdlp_version(), "ffmpeg": FFmpeg().version(), "python": platform.python_version()},
        "queue": {"connected": request.app.state.queue.ping(), "depth": request.app.state.queue.depth()},
        "jobs": counts,
        "storage": {
            "used_bytes": dir_size(s.media_dir) + dir_size(s.work_dir),
            "quota_bytes": s.max_storage_mb * 1024 * 1024,
            "disk_free_bytes": disk.free,
            "disk_total_bytes": disk.total,
        },
        "limits": {
            "retention_minutes": s.retention_minutes, "max_filesize_mb": s.max_filesize_mb,
            "max_duration_seconds": s.max_duration_seconds, "max_pending_jobs_per_user": s.max_pending_jobs_per_user,
        },
        "last_24h": {
            "completed": completed_24h,
            "failures_by_reason": [{"code": c, "count": n} for c, n in failures_24h],
            "served_from_cache": cached_24h or 0,
            "active_visitors": visitors_24h or 0,
        },
        "recent_failures": [
            {"id": j.id, "kind": j.kind, "error_code": j.error_code, "error_message": j.error_message,
             "created_at": j.created_at.isoformat()} for j in recent_failures
        ],
        "recent_audit": [
            {"action": a.action, "success": a.success, "ip": a.ip, "target": a.target_id,
             "created_at": a.created_at.isoformat()} for a in recent_audit
        ],
    }
