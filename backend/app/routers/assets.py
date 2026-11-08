"""Watermark images and processing presets."""
from __future__ import annotations

import struct

from fastapi import APIRouter, Depends, File, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import get_settings
from ..db import get_db
from ..deps import api_error, current_user, rate_limited, require_csrf
from ..jobs.cleanup import delete_media_file
from ..models import FileKind, MediaFile, ProcessingPreset, User, new_id
from ..schemas import PresetIn
from ..serializers import file_out, preset_out

router = APIRouter(prefix="/api", tags=["assets"], dependencies=[Depends(rate_limited("api", "rate_limit_per_minute"))])

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MAX_WATERMARK_DIMENSION = 4096


def parse_png_size(data: bytes) -> tuple[int, int]:
    """Validate the PNG signature and IHDR chunk; return (width, height)."""
    if len(data) < 33 or not data.startswith(PNG_MAGIC) or data[12:16] != b"IHDR":
        raise ValueError("not a PNG")
    width, height = struct.unpack(">II", data[16:24])
    if not (0 < width <= MAX_WATERMARK_DIMENSION and 0 < height <= MAX_WATERMARK_DIMENSION):
        raise ValueError("bad dimensions")
    return width, height


@router.post("/watermarks", status_code=201)
async def upload_watermark(request: Request, file: UploadFile = File(...), user: User = Depends(current_user),
                           _csrf=Depends(require_csrf), db: Session = Depends(get_db)):
    s = get_settings()
    limit = s.max_watermark_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise api_error(413, "too_large", f"Watermark images must be under {s.max_watermark_mb} MB.")
    try:
        width, height = parse_png_size(data)
    except ValueError:
        raise api_error(400, "invalid_png", "The watermark must be a PNG image up to 4096×4096 pixels.") from None
    s.ensure_dirs()
    fid = new_id()
    rel = f"{fid}.png"
    (s.watermark_dir / rel).write_bytes(data)
    name = (file.filename or "watermark.png").rsplit("/", 1)[-1][:100]
    mf = MediaFile(id=fid, user_id=user.id, kind=FileKind.WATERMARK, path=rel, filename=name,
                   mime_type="image/png", size_bytes=len(data), width=width, height=height, expires_at=None)
    db.add(mf)
    db.commit()
    audit(db, request, "watermark_upload", user_id=user.id, target_type="file", target_id=fid)
    return file_out(mf)


@router.get("/watermarks")
def list_watermarks(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(MediaFile).where(MediaFile.user_id == user.id, MediaFile.kind == FileKind.WATERMARK,
                                              MediaFile.deleted_at.is_(None))
                      .order_by(MediaFile.created_at.desc())).all()
    return {"items": [file_out(r) for r in rows]}


@router.delete("/watermarks/{file_id}")
def delete_watermark(file_id: str, request: Request, user: User = Depends(current_user),
                     _csrf=Depends(require_csrf), db: Session = Depends(get_db)):
    mf = db.get(MediaFile, file_id)
    if mf is None or mf.user_id != user.id or mf.kind != FileKind.WATERMARK:
        raise api_error(404, "not_found", "Watermark not found.")
    delete_media_file(db, mf)
    for p in db.scalars(select(ProcessingPreset).where(ProcessingPreset.watermark_file_id == file_id)).all():
        p.watermark_file_id = None
    db.commit()
    audit(db, request, "watermark_delete", user_id=user.id, target_type="file", target_id=file_id)
    return {"deleted": file_id}


def _validate_preset_watermark(db: Session, user: User, body: PresetIn) -> None:
    if body.watermark_file_id:
        wm = db.get(MediaFile, body.watermark_file_id)
        if wm is None or wm.user_id != user.id or wm.kind != FileKind.WATERMARK or wm.deleted_at is not None:
            raise api_error(400, "invalid_watermark", "Choose a watermark image you uploaded.")


def _apply(p: ProcessingPreset, body: PresetIn) -> None:
    p.name = body.name.strip()
    p.watermark_file_id = body.watermark_file_id
    p.watermark_size_pct = body.watermark_size_pct
    p.watermark_opacity = body.watermark_opacity
    p.watermark_margin_pct = body.watermark_margin_pct
    p.aspect = body.aspect
    p.fill_mode = body.fill_mode
    p.generate_thumbnails = body.thumbnails


@router.get("/presets")
def list_presets(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(ProcessingPreset).where(ProcessingPreset.user_id == user.id)
                      .order_by(ProcessingPreset.name)).all()
    return {"items": [preset_out(p) for p in rows]}


@router.post("/presets", status_code=201)
def create_preset(body: PresetIn, request: Request, user: User = Depends(current_user),
                  _csrf=Depends(require_csrf), db: Session = Depends(get_db)):
    _validate_preset_watermark(db, user, body)
    p = ProcessingPreset(user_id=user.id)
    _apply(p, body)
    db.add(p)
    db.commit()
    audit(db, request, "preset_create", user_id=user.id, target_type="preset", target_id=p.id)
    return preset_out(p)


@router.put("/presets/{preset_id}")
def update_preset(preset_id: int, body: PresetIn, request: Request, user: User = Depends(current_user),
                  _csrf=Depends(require_csrf), db: Session = Depends(get_db)):
    p = db.get(ProcessingPreset, preset_id)
    if p is None or p.user_id != user.id:
        raise api_error(404, "not_found", "Preset not found.")
    _validate_preset_watermark(db, user, body)
    _apply(p, body)
    db.commit()
    audit(db, request, "preset_update", user_id=user.id, target_type="preset", target_id=p.id)
    return preset_out(p)


@router.delete("/presets/{preset_id}")
def delete_preset(preset_id: int, request: Request, user: User = Depends(current_user),
                  _csrf=Depends(require_csrf), db: Session = Depends(get_db)):
    p = db.get(ProcessingPreset, preset_id)
    if p is None or p.user_id != user.id:
        raise api_error(404, "not_found", "Preset not found.")
    db.delete(p)
    db.commit()
    audit(db, request, "preset_delete", user_id=user.id, target_type="preset", target_id=preset_id)
    return {"deleted": preset_id}
