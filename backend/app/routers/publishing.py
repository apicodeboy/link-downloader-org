"""Publishing preparation: draft -> approved -> (submit when a verified provider exists)."""
from __future__ import annotations

import io
import zipfile

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import get_settings
from ..db import get_db
from ..deps import api_error, current_user, rate_limited, require_admin, require_csrf
from ..jobs.cleanup import file_root
from ..media.storage import resolve_stored
from ..models import FileKind, MediaFile, PublishingJob, User, utcnow
from ..publishing.providers import ProviderNotReady, get_provider
from ..schemas import PublishingJobIn, PublishingJobUpdate
from ..serializers import publishing_out

router = APIRouter(prefix="/api/publishing", tags=["publishing"],
                   dependencies=[Depends(rate_limited("api", "rate_limit_per_minute"))])


def _job(db: Session, user: User, job_id: int) -> PublishingJob:
    pj = db.get(PublishingJob, job_id)
    if pj is None or pj.user_id != user.id:
        raise api_error(404, "not_found", "Publishing job not found.")
    return pj


def _check_destinations(dest_ids: list[str]) -> None:
    known = {d.id for d in get_provider().destinations()}
    unknown = [d for d in dest_ids if d not in known]
    if unknown:
        raise api_error(400, "unknown_destination", f"Unknown destination account(s): {', '.join(unknown)}. "
                                                    "Configure accounts in PUBLISHING_ACCOUNTS.")


@router.get("/config")
def config(user: User = Depends(current_user)):
    s = get_settings()
    p = get_provider()
    return {
        "provider": p.name,
        "provider_configured": p.configured(),
        "submit_enabled": s.publishing_submit_enabled,
        "destinations": [d.__dict__ for d in p.destinations()],
    }


@router.post("/check")
def check(request: Request, user: User = Depends(require_admin), _csrf=Depends(require_csrf),
          db: Session = Depends(get_db)):
    result = get_provider().check_connection()
    audit(db, request, "publishing_check", user_id=user.id, success=bool(result.get("ok")))
    return result


@router.get("/jobs")
def list_jobs(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(PublishingJob).where(PublishingJob.user_id == user.id)
                      .order_by(PublishingJob.created_at.desc()).limit(100)).all()
    return {"items": [publishing_out(r) for r in rows]}


@router.post("/jobs", status_code=201)
def create_job(body: PublishingJobIn, request: Request, user: User = Depends(current_user),
               _csrf=Depends(require_csrf), db: Session = Depends(get_db)):
    mf = db.get(MediaFile, body.media_file_id)
    if mf is None or mf.user_id != user.id or mf.kind not in (FileKind.VIDEO, FileKind.PROCESSED):
        raise api_error(400, "invalid_file", "Choose one of your downloaded or processed videos.")
    if not mf.available:
        raise api_error(410, "expired", "That video has expired. Download or process it again.")
    _check_destinations(body.destinations)
    pj = PublishingJob(user_id=user.id, media_file_id=mf.id, provider=get_provider().name, caption=body.caption,
                       hashtags=body.hashtags, destinations=body.destinations, scheduled_at=body.scheduled_at)
    db.add(pj)
    db.commit()
    audit(db, request, "publishing_create", user_id=user.id, target_type="publishing_job", target_id=pj.id)
    return publishing_out(pj)


@router.patch("/jobs/{job_id}")
def update_job(job_id: int, body: PublishingJobUpdate, request: Request, user: User = Depends(current_user),
               _csrf=Depends(require_csrf), db: Session = Depends(get_db)):
    pj = _job(db, user, job_id)
    if pj.status not in ("draft", "approved"):
        raise api_error(409, "locked", "Only draft or approved jobs can be edited.")
    data = body.model_dump(exclude_unset=True)
    if "destinations" in data and data["destinations"] is not None:
        _check_destinations(data["destinations"])
    for k, v in data.items():
        if v is not None or k == "scheduled_at":
            setattr(pj, k, v)
    # Any edit invalidates a previous approval.
    pj.status, pj.approved_at, pj.approved_by = "draft", None, None
    db.commit()
    audit(db, request, "publishing_update", user_id=user.id, target_type="publishing_job", target_id=pj.id)
    return publishing_out(pj)


@router.post("/jobs/{job_id}/approve")
def approve(job_id: int, request: Request, user: User = Depends(current_user), _csrf=Depends(require_csrf),
            db: Session = Depends(get_db)):
    pj = _job(db, user, job_id)
    if pj.status != "draft":
        raise api_error(409, "invalid_state", "Only draft jobs can be approved.")
    if not pj.destinations:
        raise api_error(400, "no_destinations", "Select at least one destination account before approving.")
    pj.status, pj.approved_at, pj.approved_by = "approved", utcnow(), user.id
    db.commit()
    audit(db, request, "publishing_approve", user_id=user.id, target_type="publishing_job", target_id=pj.id)
    return publishing_out(pj)


@router.post("/jobs/{job_id}/cancel")
def cancel(job_id: int, request: Request, user: User = Depends(current_user), _csrf=Depends(require_csrf),
           db: Session = Depends(get_db)):
    pj = _job(db, user, job_id)
    if pj.status not in ("draft", "approved"):
        raise api_error(409, "invalid_state", "This job can no longer be cancelled.")
    pj.status = "cancelled"
    db.commit()
    audit(db, request, "publishing_cancel", user_id=user.id, target_type="publishing_job", target_id=pj.id)
    return publishing_out(pj)


@router.post("/jobs/{job_id}/submit")
def submit(job_id: int, request: Request, user: User = Depends(require_admin), _csrf=Depends(require_csrf),
           db: Session = Depends(get_db)):
    s = get_settings()
    pj = _job(db, user, job_id)
    if pj.status != "approved" or pj.approved_by is None:
        raise api_error(409, "not_approved", "Approve the job before submitting it.")
    if not s.publishing_submit_enabled:
        raise api_error(403, "submit_disabled", "Publishing is disabled on this server "
                                                "(PUBLISHING_SUBMIT_ENABLED=false).")
    provider = get_provider()
    try:
        response = provider.submit(pj, None)
    except ProviderNotReady as exc:
        audit(db, request, "publishing_submit", user_id=user.id, success=False, target_type="publishing_job",
              target_id=pj.id, reason=exc.code)
        raise api_error(501, exc.code, exc.message) from None
    pj.status, pj.provider_response, pj.provider_ref = "submitted", response, str(response.get("id", ""))
    db.commit()
    audit(db, request, "publishing_submit", user_id=user.id, target_type="publishing_job", target_id=pj.id)
    return publishing_out(pj)


@router.get("/jobs/{job_id}/package")
def package(job_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """ZIP with the video and caption.txt, ready for manual upload to any scheduler."""
    pj = _job(db, user, job_id)
    mf = db.get(MediaFile, pj.media_file_id)
    if mf is None or not mf.available:
        raise api_error(410, "expired", "The video for this job has expired.")
    path = resolve_stored(file_root(mf.kind), mf.path)
    if not path.is_file():
        raise api_error(410, "expired", "The video for this job is no longer on the server.")
    caption = pj.caption
    if pj.hashtags:
        caption = (caption.rstrip("\n") + "\n\n" if caption.strip() else "") + " ".join(pj.hashtags)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        zf.write(path, mf.filename)
        zf.writestr("caption.txt", caption.encode("utf-8"))
    buf.seek(0)
    audit(db, request, "publishing_package", user_id=user.id, target_type="publishing_job", target_id=pj.id)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="publish_{pj.id}.zip"'})
