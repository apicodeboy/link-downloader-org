"""Parent-side wrapper that runs `ytdlp_runner` in a separate, time-limited process."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path

from ..config import Settings, get_settings
from .errors import MediaError, classify_error

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def ytdlp_version() -> str:
    try:
        from yt_dlp.version import __version__

        return __version__
    except Exception:  # pragma: no cover
        return "unknown"


def run_ytdlp(
    request: dict,
    timeout: int,
    on_event: Callable[[dict], None] | None = None,
    settings: Settings | None = None,
) -> dict:
    settings = settings or get_settings()
    workdir = Path(request["workdir"])
    workdir.mkdir(parents=True, exist_ok=True, mode=0o750)
    request = {
        **request,
        "ffmpeg_location": _ffmpeg_dir(settings),
        "js_runtimes": [r.strip() for r in settings.ytdlp_js_runtimes.split(",") if r.strip()],
    }
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(workdir),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    stderr_path = workdir / "ytdlp.log"
    cmd = [sys.executable, "-s", "-m", "app.media.ytdlp_runner"]
    with open(stderr_path, "w", encoding="utf-8") as stderr_file:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr_file,
            cwd=BACKEND_ROOT,
            env=env,
            text=True,
            encoding="utf-8",
            start_new_session=True,
        )
        timed_out = threading.Event()

        def _kill() -> None:
            timed_out.set()
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

        timer = threading.Timer(timeout, _kill)
        timer.daemon = True
        timer.start()
        result: dict | None = None
        try:
            assert proc.stdin and proc.stdout
            proc.stdin.write(json.dumps(request))
            proc.stdin.close()
            for line in proc.stdout:
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if msg.get("type") == "result":
                    result = msg
                elif on_event is not None:
                    try:
                        on_event(msg)
                    except Exception:  # progress reporting must never kill the job
                        pass
            proc.wait()
        finally:
            timer.cancel()
            if proc.poll() is None:
                _kill()
                proc.wait()

    log_tail = _tail(stderr_path)
    if timed_out.is_set():
        raise MediaError("timeout", f"The job took longer than {timeout} seconds and was stopped.", log_tail)
    if result is None:
        raise classify_error(log_tail or f"yt-dlp process exited with code {proc.returncode}")
    if not result.get("ok"):
        err = classify_error(f"{result.get('error', '')}\n{log_tail}")
        # Prefer the specific error line over the log tail for classification.
        primary = classify_error(result.get("error", ""))
        if primary.code != "download_failed":
            err = MediaError(primary.code, primary.message, err.detail)
        raise err
    return result


def _ffmpeg_dir(settings: Settings) -> str | None:
    p = settings.ffmpeg_path
    if os.sep in p:
        return str(Path(p).parent)
    return None


def _tail(path: Path, max_chars: int = 4000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[-max_chars:]
