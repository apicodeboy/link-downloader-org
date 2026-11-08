"""Job status endpoints (polled by the dashboard)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..db import get_db
from ..deps import api_error, current_user, rate_limited, require_csrf
from ..limits import limits_for
from ..models import JobKind, JobStatus, MediaJob, User, utcnow
from ..serializers import job_out, personalize

router = APIRouter(prefix="/api/jobs", tags=["jobs"],
                   dependencies=[Depends(rate_limited("api", "rate_limit_per_minute"))])


def _own(db: Session, user: User, job_id: str) -> MediaJob:
    job = db.get(MediaJob, job_id)
    if job is None or job.user_id != user.id:
        raise api_error(404, "not_found", "Job not found.")
    return job


def _queue_position(db: Session, job: MediaJob) -> int | None:
    if job.status != JobStatus.QUEUED:
        return None
    ahead = db.scalar(select(func.count()).select_from(MediaJob).where(
        MediaJob.status == JobStatus.QUEUED, MediaJob.created_at < job.created_at))
    return int(ahead or 0) + 1


@router.get("")
def list_jobs(user: User = Depends(current_user), db: Session = Depends(get_db),
              status: str | None = Query(None), limit: int = Query(50, ge=1, le=200)):
    q = select(MediaJob).where(MediaJob.user_id == user.id)
    if status == "active":
        q = q.where(MediaJob.status.in_(JobStatus.ACTIVE))
    elif status:
        if status not in JobStatus.ALL:
            raise api_error(400, "invalid_status", "Unknown status filter.")
        q = q.where(MediaJob.status == status)
    jobs = db.scalars(q.order_by(MediaJob.created_at.desc()).limit(limit)).all()
    return {"items": [job_out(j) for j in jobs]}


@router.get("/{job_id}")
def get_job(job_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = _own(db, user, job_id)
    out = personalize(job_out(job), limits_for(user.role))
    out["queue_position"] = _queue_position(db, job)
    if user.role == "admin" and job.error_detail:
        out["error_detail"] = job.error_detail
    return out


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str, request: Request, user: User = Depends(current_user),
               _csrf=Depends(require_csrf), db: Session = Depends(get_db)):
    """Cancel a waiting job, or stop a download that is in progress."""
    job = _own(db, user, job_id)
    if job.status == JobStatus.QUEUED:
        job.status, job.stage, job.finished_at = JobStatus.FAILED, "Cancelled", utcnow()
        job.error_code, job.error_message = "cancelled", "Cancelled."
    elif job.status == JobStatus.DOWNLOADING and job.kind == JobKind.DOWNLOAD:
        job.cancel_requested = True
        job.stage = "Cancelling…"
    elif job.status in JobStatus.ACTIVE:
        raise api_error(409, "cannot_cancel", "This step can't be stopped part-way. It will finish shortly.")
    else:
        raise api_error(409, "not_active", "This job has already finished.")
    db.commit()
    audit(db, request, "job_cancel", user_id=user.id, target_type="job", target_id=job.id)
    return job_out(job)
