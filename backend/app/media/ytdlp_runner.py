"""Isolated yt-dlp process.

Started by `ytdlp.run_ytdlp` as `python -m app.media.ytdlp_runner` with an argument array
(never a shell). It reads one JSON request on stdin and writes JSON lines on stdout:
progress events and one final result. Before importing yt-dlp it installs the socket
guard, so every connection yt-dlp makes is checked against the public-IP policy.

Hardening applied here:
* generic page extractor disabled (no arbitrary page scraping, only real site extractors)
* proxies from the environment ignored, no config files, no cookies, no cache directory
* HLS downloaded natively (FFmpeg is only used on local files)
* hard file-size cap enforced while bytes arrive, not only from advertised sizes
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


class _Emitter:
    def __init__(self, stream):
        self.stream = stream

    def __call__(self, obj: dict) -> None:
        self.stream.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
        self.stream.flush()


class _Logger:
    def __init__(self):
        self.errors: list[str] = []

    def debug(self, msg):
        if not msg.startswith("[debug] "):
            print(msg, file=sys.stderr)

    def info(self, msg):
        print(msg, file=sys.stderr)

    def warning(self, msg):
        print(msg, file=sys.stderr)

    def error(self, msg):
        self.errors.append(str(msg))
        print(msg, file=sys.stderr)


class SizeLimitExceeded(Exception):
    pass


class ContentRejected(Exception):
    pass


def _first_entry(info: dict) -> dict:
    if info.get("_type") in ("playlist", "multi_video") and info.get("entries") is not None:
        entries = [e for e in info["entries"] if e]
        if not entries:
            raise ContentRejected("No video found in this post")
        first = dict(entries[0])
        first["_entry_count"] = info.get("playlist_count") or len(entries)
        return first
    return info


def _check_content(info: dict, max_duration: int) -> None:
    if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
        raise ContentRejected("live event: live streams can't be downloaded")
    duration = info.get("duration")
    if isinstance(duration, (int, float)) and max_duration and duration > max_duration:
        raise ContentRejected(
            f"exceeds size limit: video is {int(duration)}s long; the limit is {max_duration}s"
        )


def _base_opts(req: dict, logger: _Logger) -> dict:
    workdir = req["workdir"]
    return {
        "logger": logger,
        "quiet": True,
        "noprogress": True,
        "color": {"stdout": "never", "stderr": "never"},
        "noplaylist": True,
        "playlist_items": "1",
        "allowed_extractors": ["default", "-generic"],
        "cachedir": False,
        "proxy": "",
        "socket_timeout": int(req.get("socket_timeout", 20)),
        "retries": 3,
        "fragment_retries": 5,
        "extractor_retries": 2,
        "paths": {"home": workdir, "temp": workdir},
        "outtmpl": {"default": "media.%(ext)s"},
        "restrictfilenames": True,
        "windowsfilenames": True,
        "overwrites": True,
        "ffmpeg_location": req.get("ffmpeg_location") or None,
        "hls_prefer_native": True,
        "check_formats": False,
        "live_from_start": False,
        "consoletitle": False,
        "format_sort": ["res", "vcodec:h264", "acodec:aac", "ext:mp4:m4a", "tbr"],
        "js_runtimes": {name: {} for name in req.get("js_runtimes") or ["deno"]},
        "remote_components": set(),  # never download solver code at runtime
    }


def analyze(req: dict, emit) -> dict:
    import yt_dlp
    from app.media.formats import summarize_info

    logger = _Logger()
    opts = _base_opts(req, logger)
    opts.update({
        "skip_download": True,
        "writethumbnail": True,
        "outtmpl": {"default": "thumb.%(ext)s", "thumbnail": "thumb.%(ext)s"},
        "postprocessors": [{"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"}],
    })
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(req["url"], download=True)
        info = ydl.sanitize_info(_first_entry(info))
    if any(f.get("has_drm") for f in info.get("formats") or []) and not [
        f for f in info.get("formats") or [] if not f.get("has_drm")
    ]:
        raise ContentRejected("DRM protected: all formats of this video are DRM-protected")
    thumbs = sorted(Path(req["workdir"]).glob("thumb*.*"))
    return {
        "summary": summarize_info(info),
        "thumbnail": str(thumbs[0]) if thumbs else None,
        "warnings": logger.errors,
    }


def download(req: dict, emit) -> dict:
    import yt_dlp
    from app.media.formats import summarize_info

    logger = _Logger()
    max_bytes = int(req["max_filesize"])
    state = {"last": 0.0, "done_streams": 0, "current": None}

    def hook(d: dict) -> None:
        status = d.get("status")
        filename = d.get("filename")
        if status == "downloading":
            if filename != state["current"]:
                state["current"] = filename
            downloaded = int(d.get("downloaded_bytes") or 0)
            if downloaded > max_bytes:
                raise SizeLimitExceeded("File is larger than max-filesize")
            now = time.monotonic()
            if now - state["last"] >= 0.5:
                state["last"] = now
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                emit({
                    "type": "progress",
                    "stream": state["done_streams"],
                    "downloaded": downloaded,
                    "total": int(total) if total else None,
                    "speed": d.get("speed"),
                    "eta": d.get("eta"),
                })
        elif status == "finished":
            state["done_streams"] += 1
            emit({"type": "progress", "stream": state["done_streams"], "stream_finished": True})

    def pp_hook(d: dict) -> None:
        if d.get("status") == "started":
            emit({"type": "postprocess", "name": d.get("postprocessor")})

    opts = _base_opts(req, logger)
    opts.update({
        "format": req["format"],
        "merge_output_format": "mp4",
        "outtmpl": {"default": "video.%(ext)s"},
        "max_filesize": max_bytes,
        "progress_hooks": [hook],
        "postprocessor_hooks": [pp_hook],
        "writethumbnail": False,
    })
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = _first_entry(ydl.extract_info(req["url"], download=False))
        _check_content(info, int(req.get("max_duration") or 0))
        info = ydl.process_ie_result(info, download=True)
        info = ydl.sanitize_info(info)
    downloads = info.get("requested_downloads") or []
    filepath = downloads[0].get("filepath") if downloads else None
    if not filepath or not Path(filepath).is_file():
        candidates = sorted(Path(req["workdir"]).glob("video.*"))
        candidates = [c for c in candidates if not c.name.endswith((".part", ".ytdl"))]
        if not candidates:
            raise ContentRejected("No video could be found: yt-dlp produced no output file")
        filepath = str(candidates[0])
    if Path(filepath).stat().st_size > max_bytes:
        raise SizeLimitExceeded("File is larger than max-filesize")
    return {"filepath": filepath, "summary": summarize_info(info), "warnings": logger.errors}


def main() -> int:
    # Keep a private handle on the real stdout for our JSON protocol, then point fd 1 at
    # stderr so stray prints from libraries can't corrupt the protocol.
    real_stdout = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    os.dup2(2, 1)
    emit = _Emitter(real_stdout)

    from app.security import net_guard

    net_guard.install()
    try:
        req = json.loads(sys.stdin.read())
        os.chdir(req["workdir"])
        if req.get("mode") == "analyze":
            result = analyze(req, emit)
        elif req.get("mode") == "download":
            result = download(req, emit)
        else:
            raise ValueError("unknown mode")
        emit({"type": "result", "ok": True, **result})
        return 0
    except BaseException as exc:  # noqa: BLE001 - report everything to the parent
        emit({"type": "result", "ok": False, "error": f"{type(exc).__name__}: {exc}"})
        return 1


if __name__ == "__main__":
    sys.exit(main())
