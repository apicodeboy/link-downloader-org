"""Turn yt-dlp's format list into the resolution options shown in the UI."""
from __future__ import annotations

from typing import Any

BEST = "best"
BEST_SELECTOR = "bv*+ba/b"
# Prefer higher resolution, then H.264/AAC in MP4 (plays everywhere), then bitrate.
FORMAT_SORT = ["res", "vcodec:h264", "acodec:aac", "ext:mp4:m4a", "tbr"]
_SKIP_PROTOCOLS = {"mhtml"}  # storyboard images


def _size(f: dict[str, Any]) -> int | None:
    v = f.get("filesize") or f.get("filesize_approx")
    return int(v) if isinstance(v, (int, float)) and v > 0 else None


def _has_video(f: dict[str, Any]) -> bool:
    if f.get("vcodec") == "none":
        return False
    return bool(f.get("height") or f.get("width") or (f.get("vcodec") not in (None, "none")))


def _short_codec(c: str | None) -> str | None:
    if not c or c == "none":
        return None
    c = c.lower()
    for prefix, name in (("avc", "H.264"), ("h264", "H.264"), ("hev", "H.265"), ("hvc", "H.265"),
                         ("h265", "H.265"), ("vp9", "VP9"), ("vp09", "VP9"), ("av01", "AV1"), ("vp8", "VP8")):
        if c.startswith(prefix):
            return name
    return c.split(".")[0]


def build_format_options(info: dict[str, Any]) -> list[dict[str, Any]]:
    formats = info.get("formats") or ([info] if info.get("url") else [])
    best_audio = max(
        (f for f in formats if f.get("vcodec") == "none" and f.get("acodec") not in (None, "none")),
        key=lambda f: (f.get("abr") or f.get("tbr") or 0),
        default=None,
    )
    by_height: dict[int, dict[str, Any]] = {}
    for f in formats:
        if f.get("has_drm") or f.get("protocol") in _SKIP_PROTOCOLS or not f.get("format_id"):
            continue
        if not _has_video(f):
            continue
        height = int(f.get("height") or 0)
        rank = (
            1 if _short_codec(f.get("vcodec")) == "H.264" else 0,
            1 if f.get("acodec") not in ("none",) else 0,
            f.get("tbr") or 0,
        )
        current = by_height.get(height)
        if current is None or rank > current["_rank"]:
            by_height[height] = {"_rank": rank, "f": f}

    options: list[dict[str, Any]] = []
    for height in sorted(by_height, reverse=True):
        f = by_height[height]["f"]
        video_only = f.get("acodec") == "none"
        size = _size(f)
        if size and video_only and best_audio is not None and _size(best_audio):
            size += _size(best_audio) or 0
        fps = f.get("fps")
        label = f"{height}p" if height else (f.get("format_note") or f.get("format_id"))
        if fps and fps > 31:
            label += f"{round(fps)}"
        codec = _short_codec(f.get("vcodec"))
        options.append({
            "format_id": str(f["format_id"]),
            "label": label,
            "height": height or None,
            "width": f.get("width"),
            "fps": fps,
            "ext": f.get("ext"),
            "vcodec": codec,
            "has_audio": not video_only or best_audio is not None,
            "needs_merge": video_only,
            "filesize": size,
        })
    best = {
        "format_id": BEST, "label": "Best available", "height": options[0]["height"] if options else None,
        "width": None, "fps": None, "ext": "mp4", "vcodec": None, "has_audio": True,
        "needs_merge": False, "filesize": options[0]["filesize"] if options else None,
    }
    return [best, *options]


def selector_for(option: dict[str, Any]) -> str:
    """yt-dlp format selector for an option that was offered to the user."""
    if option["format_id"] == BEST:
        return BEST_SELECTOR
    fid = option["format_id"]
    h = option.get("height")
    fallback = f"bv*[height<={h}]+ba/b[height<={h}]" if h else BEST_SELECTOR
    if option.get("needs_merge"):
        return f"{fid}+ba[ext=m4a]/{fid}+ba/{fallback}"
    return f"{fid}/{fallback}"


def summarize_info(info: dict[str, Any]) -> dict[str, Any]:
    """Small, JSON-safe subset of yt-dlp's info dict that we store and show."""
    from .captions import extract_caption

    cap = extract_caption(info)
    duration = info.get("duration")
    return {
        **cap,
        "id": info.get("id"),
        "extractor": info.get("extractor_key") or info.get("extractor"),
        "webpage_url": info.get("webpage_url") or info.get("original_url"),
        "duration": float(duration) if isinstance(duration, (int, float)) else None,
        "upload_date": info.get("upload_date"),
        "timestamp": info.get("timestamp"),
        "view_count": info.get("view_count"),
        "like_count": info.get("like_count"),
        "width": info.get("width"),
        "height": info.get("height"),
        "is_live": bool(info.get("is_live")),
        "formats": build_format_options(info),
        "entry_count": info.get("_entry_count", 1),
    }
