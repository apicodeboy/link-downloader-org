"""Job status endpoints (polled by the dashboard)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import api_error, current_user, rate_limited
from ..models import JobStatus, MediaJob, User
from ..serializers import job_out

router = APIRouter(prefix="/api/jobs", tags=["jobs"],
                   dependencies=[Depends(rate_limited("api", "rate_limit_per_minute"))])


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
    job = db.get(MediaJob, job_id)
    if job is None or job.user_id != user.id:
        raise api_error(404, "not_found", "Job not found.")
    out = job_out(job)
    if user.role == "admin" and job.error_detail:
        out["error_detail"] = job.error_detail
    return out
