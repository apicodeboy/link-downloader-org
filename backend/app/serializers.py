"""Convert database rows into API responses."""
from __future__ import annotations

from .models import DownloadHistory, MediaFile, MediaJob, ProcessingPreset, PublishingJob


def _dt(v):
    return v.isoformat() if v else None


def job_out(job: MediaJob) -> dict:
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "progress": round(job.progress or 0, 3),
        "stage": job.stage,
        "source_url": job.source_url,
        "resolved_url": job.resolved_url,
        "platform": job.platform,
        "parent_job_id": job.parent_job_id,
        "input_file_id": job.input_file_id,
        "options": job.options or {},
        "result": job.result,
        "error": {"code": job.error_code, "message": job.error_message} if job.error_code else None,
        "cancel_requested": bool(job.cancel_requested),
        "created_at": _dt(job.created_at),
        "started_at": _dt(job.started_at),
        "finished_at": _dt(job.finished_at),
    }


def personalize(out: dict, limits) -> dict:
    """Recompute 'too long' for this viewer (guests and admins have different limits)."""
    result = out.get("result")
    if out.get("kind") == "analyze" and isinstance(result, dict):
        result = dict(result)
        duration = result.get("duration") or 0
        result["max_duration_seconds"] = limits.max_duration_seconds
        result["too_long"] = bool(duration and duration > limits.max_duration_seconds)
        result["process_max_duration_seconds"] = limits.process_max_duration_seconds
        out["result"] = result
    return out


def file_out(mf: MediaFile) -> dict:
    return {
        "id": mf.id,
        "kind": mf.kind,
        "job_id": mf.job_id,
        "parent_file_id": mf.parent_file_id,
        "filename": mf.filename,
        "mime_type": mf.mime_type,
        "size_bytes": mf.size_bytes,
        "width": mf.width,
        "height": mf.height,
        "duration": mf.duration,
        "vcodec": mf.vcodec,
        "acodec": mf.acodec,
        "has_audio": mf.acodec is not None if mf.kind in ("video", "processed") else None,
        "available": mf.available,
        "created_at": _dt(mf.created_at),
        "expires_at": _dt(mf.expires_at),
        "url": f"/api/media/{mf.id}/file",
    }


def history_out(h: DownloadHistory, mf: MediaFile | None, thumb_id: str | None) -> dict:
    return {
        "id": h.id,
        "job_id": h.job_id,
        "kind": h.kind,
        "status": h.status,
        "source_url": h.source_url,
        "platform": h.platform,
        "title": h.title,
        "format_label": h.format_label,
        "size_bytes": h.size_bytes,
        "error_message": h.error_message,
        "created_at": _dt(h.created_at),
        "file": file_out(mf) if mf else None,
        "thumbnail_file_id": thumb_id,
    }


def preset_out(p: ProcessingPreset) -> dict:
    return {
        "id": p.id, "name": p.name, "watermark_file_id": p.watermark_file_id,
        "watermark_size_pct": p.watermark_size_pct, "watermark_opacity": p.watermark_opacity,
        "watermark_margin_pct": p.watermark_margin_pct, "watermark_position": p.watermark_position,
        "aspect": p.aspect, "fill_mode": p.fill_mode, "thumbnails": p.generate_thumbnails,
        "created_at": _dt(p.created_at), "updated_at": _dt(p.updated_at),
    }


def publishing_out(p: PublishingJob) -> dict:
    return {
        "id": p.id, "media_file_id": p.media_file_id, "provider": p.provider, "caption": p.caption,
        "hashtags": p.hashtags or [], "destinations": p.destinations or [], "scheduled_at": _dt(p.scheduled_at),
        "status": p.status, "approved_at": _dt(p.approved_at), "provider_ref": p.provider_ref,
        "error": p.error, "created_at": _dt(p.created_at), "updated_at": _dt(p.updated_at),
    }
