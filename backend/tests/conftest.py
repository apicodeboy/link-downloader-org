"""Shared test fixtures. No test touches the internet: DNS and yt-dlp are faked, and
sample media is generated locally with FFmpeg (synthetic test patterns we own)."""
from __future__ import annotations

import os
import shutil
import struct
import subprocess
import zlib
from pathlib import Path

import pytest

_LOCAL_FFMPEG = Path.home() / ".local/opt/ffmpeg/bin"
if not shutil.which("ffmpeg") and (_LOCAL_FFMPEG / "ffmpeg").exists():
    os.environ.setdefault("FFMPEG_PATH", str(_LOCAL_FFMPEG / "ffmpeg"))
    os.environ.setdefault("FFPROBE_PATH", str(_LOCAL_FFMPEG / "ffprobe"))

FFMPEG = os.environ.get("FFMPEG_PATH", "ffmpeg")
HAS_FFMPEG = bool(shutil.which(FFMPEG))
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg not installed")

FIXTURES = Path(__file__).parent / "fixtures"
PASSWORD = "Correct-Horse-Battery-9"


def make_png(width: int = 120, height: int = 40, rgba=(255, 255, 255, 200)) -> bytes:
    raw = b"".join(b"\x00" + bytes(rgba) * width for _ in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    # Most tests exercise the stricter login-required mode; test_open_mode.py covers open access.
    monkeypatch.setenv("REQUIRE_LOGIN", "true")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://testserver")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "1000")
    monkeypatch.setenv("ANALYZE_RATE_LIMIT_PER_MINUTE", "1000")
    monkeypatch.setenv("LOGIN_RATE_LIMIT_PER_MINUTE", "1000")
    from app.config import Settings, get_settings

    # Never read the developer's backend/.env during tests.
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    get_settings.cache_clear()
    s = get_settings()
    s.ensure_dirs()
    yield s
    get_settings.cache_clear()


@pytest.fixture
def queue():
    from app.jobs.queue import InlineQueue

    return InlineQueue(run=False)


@pytest.fixture
def app(settings, queue):
    from app.db import create_all
    from app.main import create_app
    from app.security.ratelimit import RateLimiter

    application = create_app(settings, queue=queue, rate_limiter=RateLimiter(None))
    create_all()
    return application


@pytest.fixture
def admin(app):
    from app.db import session_scope
    from app.models import User
    from app.security.passwords import hash_password

    with session_scope() as db:
        user = User(username="admin", password_hash=hash_password(PASSWORD), role="admin")
        db.add(user)
        db.flush()
        return user.id


@pytest.fixture
def anon_client(app):
    from fastapi.testclient import TestClient

    with TestClient(app, base_url="https://testserver") as c:
        yield c


@pytest.fixture
def client(anon_client, admin):
    r = anon_client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD},
                         headers={"Origin": "https://testserver"})
    assert r.status_code == 200, r.text
    anon_client.headers.update({"X-CSRF-Token": r.json()["csrf_token"], "Origin": "https://testserver"})
    return anon_client


@pytest.fixture(scope="session")
def sample_media(tmp_path_factory):
    """Synthetic sample clips generated locally (test pattern + tone)."""
    if not HAS_FFMPEG:
        pytest.skip("FFmpeg not installed")
    d = tmp_path_factory.mktemp("media")
    mp4 = d / "sample.mp4"
    mkv = d / "sample_mjpeg.mkv"
    silent = d / "silent.mp4"
    base = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y"]
    subprocess.run(base + ["-f", "lavfi", "-i", "testsrc=size=640x360:rate=25", "-f", "lavfi", "-i",
                           "sine=frequency=440:sample_rate=44100", "-t", "2", "-c:v", "mpeg4", "-q:v", "5",
                           "-c:a", "aac", "-shortest", str(mp4)], check=True)
    subprocess.run(base + ["-f", "lavfi", "-i", "testsrc=size=320x240:rate=15", "-f", "lavfi", "-i",
                           "sine=frequency=220", "-t", "1", "-c:v", "mjpeg", "-c:a", "aac", "-shortest", str(mkv)],
                   check=True)
    subprocess.run(base + ["-f", "lavfi", "-i", "testsrc=size=360x640:rate=25", "-t", "1", "-c:v", "mpeg4",
                           str(silent)], check=True)
    jpg = d / "thumb.jpg"
    subprocess.run(base + ["-i", str(mp4), "-frames:v", "1", str(jpg)], check=True)
    return {"mp4": mp4, "mkv": mkv, "silent": silent, "jpg": jpg}
