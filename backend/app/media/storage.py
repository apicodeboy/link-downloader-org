"""File-system layout, safe paths, and disk limits."""
from __future__ import annotations

import os
import re
import shutil
import unicodedata
from pathlib import Path

from ..config import Settings, get_settings
from .errors import MediaError

MIME_BY_EXT = {
    ".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm", ".mkv": "video/x-matroska",
    ".mov": "video/quicktime", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".webp": "image/webp",
}


def mime_for(path: Path | str) -> str:
    return MIME_BY_EXT.get(Path(path).suffix.lower(), "application/octet-stream")


def safe_filename(title: str | None, fallback: str, ext: str) -> str:
    """ASCII-only, filesystem-safe download name derived from the video title."""
    base = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode()
    base = re.sub(r"[^A-Za-z0-9._ -]+", "", base).strip().replace(" ", "_")
    base = re.sub(r"_+", "_", base).strip("._-")[:80] or fallback
    return f"{base}.{ext.lstrip('.')}"


def resolve_stored(root: Path, relative: str) -> Path:
    """Turn a stored relative path into an absolute one, refusing anything outside root."""
    root = root.resolve()
    candidate = (root / relative).resolve()
    if candidate != root and root not in candidate.parents:
        raise MediaError("invalid_path", "Invalid file path.")
    return candidate


def dir_size(path: Path) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(dirpath, f)).st_size
            except OSError:
                pass
    return total


def check_disk_capacity(settings: Settings | None = None) -> None:
    """Refuse new work when the app's storage quota or the disk's free space is exhausted."""
    s = settings or get_settings()
    s.ensure_dirs()
    used = dir_size(s.media_dir) + dir_size(s.work_dir)
    if used >= s.max_storage_mb * 1024 * 1024:
        raise MediaError(
            "storage_full",
            "The app's storage quota is full. Delete old files or wait for automatic cleanup.",
        )
    free = shutil.disk_usage(s.data_dir).free
    if free < s.min_free_disk_mb * 1024 * 1024:
        raise MediaError("disk_full", "The server is low on disk space, so new downloads are paused.")


def remove_tree(path: Path, root: Path) -> None:
    """Delete a directory only if it is inside root."""
    path, root = path.resolve(), root.resolve()
    if path == root or root not in path.parents:
        return
    shutil.rmtree(path, ignore_errors=True)
