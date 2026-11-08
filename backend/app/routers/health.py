"""Health and status endpoints."""
from __future__ import annotations

import platform
import shutil

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import current_user, require_admin
from ..media.ffmpeg import FFmpeg
from ..media.storage import dir_size
from ..media.ytdlp import ytdlp_version
from ..models import AuditLog, JobStatus, MediaJob, User

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
        "recent_failures": [
            {"id": j.id, "kind": j.kind, "error_code": j.error_code, "error_message": j.error_message,
             "created_at": j.created_at.isoformat()} for j in recent_failures
        ],
        "recent_audit": [
            {"action": a.action, "success": a.success, "ip": a.ip, "target": a.target_id,
             "created_at": a.created_at.isoformat()} for a in recent_audit
        ],
    }
