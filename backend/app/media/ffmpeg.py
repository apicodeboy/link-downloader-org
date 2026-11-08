"""FFmpeg / ffprobe helpers. Every call uses an argument list (no shell) and a timeout."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ..config import Settings, get_settings
from .errors import MediaError

MP4_VIDEO_CODECS = {"h264", "hevc", "av1", "mpeg4"}
MP4_AUDIO_CODECS = {"aac", "mp3", "alac"}
MP4_CONTAINERS = ("mov,mp4,m4a,3gp,3g2,mj2",)


@dataclass
class ProbeResult:
    format_name: str
    duration: float | None
    width: int | None
    height: int | None
    vcodec: str | None
    acodec: str | None
    rotation: int
    size: int

    @property
    def display_size(self) -> tuple[int | None, int | None]:
        if self.rotation % 180 == 90:
            return self.height, self.width
        return self.width, self.height


def _run(cmd: list[str], timeout: int, what: str) -> subprocess.CompletedProcess:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise MediaError("timeout", f"{what} took longer than {timeout} seconds and was stopped.") from None
    except FileNotFoundError:
        raise MediaError("ffmpeg_missing", "FFmpeg is not installed on the server.", cmd[0]) from None
    if proc.returncode != 0:
        tail = (proc.stderr or "")[-3000:]
        raise MediaError("ffmpeg_failed", f"{what} failed: {_summarize_ffmpeg_error(tail)}", tail)
    return proc


def _summarize_ffmpeg_error(stderr: str) -> str:
    lines = [ln.strip() for ln in stderr.splitlines() if ln.strip()]
    for ln in reversed(lines):
        low = ln.lower()
        if any(k in low for k in ("invalid data", "no such file", "error", "not supported", "could not", "unable")):
            return ln[:300]
    return lines[-1][:300] if lines else "unknown FFmpeg error"


class FFmpeg:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.ffmpeg = self.settings.ffmpeg_path
        self.ffprobe = self.settings.ffprobe_path

    def available(self) -> bool:
        return bool(shutil.which(self.ffmpeg)) and bool(shutil.which(self.ffprobe))

    def version(self) -> str | None:
        try:
            out = subprocess.run([self.ffmpeg, "-hide_banner", "-version"], capture_output=True, text=True, timeout=10)
            return out.stdout.splitlines()[0] if out.stdout else None
        except (OSError, subprocess.TimeoutExpired):
            return None

    # ---------------------------------------------------------------- probing
    def probe(self, path: Path, timeout: int = 60) -> ProbeResult:
        if not Path(path).is_file():
            raise MediaError("file_missing", "The media file no longer exists on the server.")
        proc = _run(
            [self.ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
            timeout, "Reading the video",
        )
        try:
            data = json.loads(proc.stdout or "{}")
        except json.JSONDecodeError:
            raise MediaError("invalid_media", "The file is not a readable video.") from None
        streams = data.get("streams") or []
        v = next((s for s in streams if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")), None)
        a = next((s for s in streams if s.get("codec_type") == "audio"), None)
        if v is None:
            raise MediaError("invalid_media", "The file has no video stream.")
        fmt = data.get("format") or {}
        rotation = 0
        for sd in v.get("side_data_list") or []:
            if "rotation" in sd:
                rotation = int(abs(float(sd["rotation"]))) % 360
        if not rotation and (v.get("tags") or {}).get("rotate"):
            rotation = int(v["tags"]["rotate"]) % 360

        def _f(x):
            try:
                return float(x)
            except (TypeError, ValueError):
                return None

        return ProbeResult(
            format_name=fmt.get("format_name", ""),
            duration=_f(fmt.get("duration")) or _f(v.get("duration")),
            width=v.get("width"),
            height=v.get("height"),
            vcodec=v.get("codec_name"),
            acodec=a.get("codec_name") if a else None,
            rotation=rotation,
            size=int(fmt.get("size") or os.path.getsize(path)),
        )

    # ---------------------------------------------------------------- encoders
    def video_encoder_args(self) -> list[str]:
        args = list(_encoder_args(self.ffmpeg, self.settings.ffmpeg_video_encoder))
        if self.settings.ffmpeg_threads > 0:
            args += ["-threads", str(self.settings.ffmpeg_threads)]
        return args

    # ---------------------------------------------------------------- MP4 output
    def ensure_mp4(self, src: Path, dst: Path, timeout: int) -> ProbeResult:
        """Write an MP4 to dst: stream-copy when the codecs allow it, re-encode otherwise."""
        info = self.probe(src)
        copy_ok = info.vcodec in MP4_VIDEO_CODECS and (info.acodec is None or info.acodec in MP4_AUDIO_CODECS)
        if copy_ok:
            cmd = [self.ffmpeg, "-hide_banner", "-nostdin", "-y", "-i", str(src),
                   "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy", "-movflags", "+faststart"]
            if info.vcodec == "hevc":
                cmd += ["-tag:v", "hvc1"]
            cmd += ["-f", "mp4", str(dst)]
            try:
                _run(cmd, timeout, "Converting to MP4")
                return self.probe(dst)
            except MediaError as exc:
                if exc.code == "timeout":
                    raise
        cmd = [self.ffmpeg, "-hide_banner", "-nostdin", "-y", "-i", str(src),
               "-map", "0:v:0", "-map", "0:a:0?", *self.video_encoder_args(),
               "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p",
               *self._audio_args(info), "-movflags", "+faststart", "-f", "mp4", str(dst)]
        _run(cmd, timeout, "Converting to MP4")
        return self.probe(dst)

    def _audio_args(self, info: ProbeResult) -> list[str]:
        if info.acodec is None:
            return ["-an"]
        if info.acodec == "aac":
            return ["-c:a", "copy"]
        return ["-c:a", "aac", "-b:a", "192k"]

    # ---------------------------------------------------------------- processing
    def process(self, src: Path, dst: Path, *, aspect: str, fill_mode: str, watermark: Path | None,
                watermark_size_pct: float, watermark_opacity: float, watermark_margin_pct: float,
                timeout: int) -> ProbeResult:
        info = self.probe(src)
        w, h = info.display_size
        if not w or not h:
            raise MediaError("invalid_media", "Could not read the video dimensions.")
        graph, out_w, out_h = build_filter_graph(
            src_w=w, src_h=h, aspect=aspect, fill_mode=fill_mode, has_watermark=watermark is not None,
            watermark_size_pct=watermark_size_pct, watermark_opacity=watermark_opacity,
            watermark_margin_pct=watermark_margin_pct,
        )
        cmd = [self.ffmpeg, "-hide_banner", "-nostdin", "-y", "-i", str(src)]
        if watermark is not None:
            cmd += ["-i", str(watermark)]
        cmd += ["-filter_complex", graph, "-map", "[out]", "-map", "0:a:0?",
                *self.video_encoder_args(), *self._audio_args(info),
                "-movflags", "+faststart", "-f", "mp4", str(dst)]
        _run(cmd, timeout, "Processing the video")
        return self.probe(dst)

    def thumbnails(self, src: Path, outdir: Path, duration: float | None, count: int = 3, timeout: int = 60) -> list[Path]:
        outdir.mkdir(parents=True, exist_ok=True)
        if duration and duration > 1:
            times = [duration * (i + 1) / (count + 1) for i in range(count)]
        else:
            times = [0.0]
        paths: list[Path] = []
        for i, t in enumerate(times, 1):
            out = outdir / f"thumb_{i}.jpg"
            _run([self.ffmpeg, "-hide_banner", "-nostdin", "-y", "-ss", f"{t:.3f}", "-i", str(src),
                  "-frames:v", "1", "-vf", "scale='min(720,iw)':-2", "-q:v", "3", str(out)],
                 timeout, "Generating thumbnails")
            if out.is_file():
                paths.append(out)
        return paths


def _even(x: float) -> int:
    return max(2, int(round(x / 2)) * 2)


def build_filter_graph(*, src_w: int, src_h: int, aspect: str, fill_mode: str, has_watermark: bool,
                       watermark_size_pct: float, watermark_opacity: float,
                       watermark_margin_pct: float) -> tuple[str, int, int]:
    """Build an FFmpeg filter_complex graph. Returns (graph, output_width, output_height).

    9:16 conversion always fits the whole original frame inside the canvas (letterbox
    with a blurred or black background); it never crops, so creator watermarks and
    on-screen credits in the original video stay visible.
    """
    parts: list[str] = []
    if aspect == "9:16":
        out_w, out_h = (1080, 1920) if max(src_w, src_h) >= 1000 else (720, 1280)
        if fill_mode == "black":
            parts.append(
                f"[0:v]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,"
                f"scale=trunc(iw/2)*2:trunc(ih/2)*2,"
                f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1[base]"
            )
        else:
            sw, sh = out_w // 4, out_h // 4
            parts.append(
                f"[0:v]split=2[bg0][fg0];"
                f"[bg0]scale={sw}:{sh}:force_original_aspect_ratio=increase,crop={sw}:{sh},"
                f"gblur=sigma=12,scale={out_w}:{out_h},setsar=1[bg];"
                f"[fg0]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,"
                f"scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2[base]"
            )
    elif aspect == "original":
        out_w, out_h = _even(src_w), _even(src_h)
        parts.append(f"[0:v]scale={out_w}:{out_h},setsar=1[base]")
    else:
        raise MediaError("invalid_options", f"Unknown aspect ratio '{aspect}'.")

    if has_watermark:
        wm_w = _even(out_w * min(max(watermark_size_pct, 2.0), 50.0) / 100.0)
        wm_max_h = _even(out_h * 0.4)
        opacity = min(max(watermark_opacity, 0.05), 1.0)
        margin = int(round(out_w * min(max(watermark_margin_pct, 0.0), 20.0) / 100.0))
        parts.append(
            f"[1:v]format=rgba,scale={wm_w}:{wm_max_h}:force_original_aspect_ratio=decrease,"
            f"colorchannelmixer=aa={opacity:.3f}[wm]"
        )
        parts.append(f"[base][wm]overlay=W-w-{margin}:H-h-{margin}:format=auto,format=yuv420p[out]")
    else:
        parts.append("[base]format=yuv420p[out]")
    return ";".join(parts), out_w, out_h


@lru_cache(maxsize=4)
def _encoder_args(ffmpeg: str, preference: str) -> tuple[str, ...]:
    presets = {
        "libx264": ("-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"),
        "h264_videotoolbox": ("-c:v", "h264_videotoolbox", "-q:v", "55", "-pix_fmt", "yuv420p"),
        "mpeg4": ("-c:v", "mpeg4", "-q:v", "3", "-pix_fmt", "yuv420p"),
    }
    if preference != "auto":
        return presets.get(preference, ("-c:v", preference))
    try:
        out = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        out = ""
    for name in ("libx264", "h264_videotoolbox", "mpeg4"):
        if f" {name} " in out:
            return presets[name]
    return presets["libx264"]
