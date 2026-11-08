"""Application settings, loaded from environment variables (and an optional .env file).

Every setting has a safe default for local development. Production values belong in
/etc/video-downloader/video-downloader.env on the server, never in Git.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SUPPORTED_DOMAINS = [
    # X / Twitter
    "x.com", "twitter.com", "t.co",
    # Instagram
    "instagram.com",
    # Facebook
    "facebook.com", "fb.watch", "fb.com",
    # TikTok
    "tiktok.com",
    # YouTube (incl. Shorts)
    "youtube.com", "youtu.be",
    # Reddit
    "reddit.com", "redd.it",
]

# Hosts whose links are short/share links that must be expanded (safely) before yt-dlp runs.
DEFAULT_SHORTLINK_HOSTS = ["t.co", "vm.tiktok.com", "vt.tiktok.com", "fb.watch", "redd.it"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_name: str = "Video Downloader"

    # Storage
    database_url: str = "sqlite:///./data/app.db"
    redis_url: str = "redis://127.0.0.1:6379/0"
    queue_name: str = "video-downloader"
    data_dir: Path = Path("./data")

    # Sessions / auth
    session_cookie_name: str = "vd_session"
    session_cookie_secure: bool = True
    session_ttl_hours: int = 12
    session_idle_minutes: int = 120
    login_max_failures: int = 5
    login_lockout_minutes: int = 15
    # Comma-separated list of origins allowed to make state-changing requests
    # (e.g. "https://videos.example.com"). Empty = only same-origin checks via CSRF token.
    allowed_origins: str = ""

    # Rate limits (requests per minute per client IP)
    rate_limit_per_minute: int = 60
    analyze_rate_limit_per_minute: int = 10
    login_rate_limit_per_minute: int = 5

    # Media limits
    retention_minutes: int = 60
    max_filesize_mb: int = 500
    max_duration_seconds: int = 1800
    analyze_timeout_seconds: int = 90
    download_timeout_seconds: int = 900
    process_timeout_seconds: int = 900
    max_storage_mb: int = 5000
    min_free_disk_mb: int = 2000
    max_pending_jobs_per_user: int = 5
    max_watermark_mb: int = 5

    # URL policy
    supported_domains: list[str] = Field(default_factory=lambda: list(DEFAULT_SUPPORTED_DOMAINS))
    shortlink_hosts: list[str] = Field(default_factory=lambda: list(DEFAULT_SHORTLINK_HOSTS))
    # If true, hosts outside supported_domains are accepted when yt-dlp has a dedicated
    # (non-generic) extractor for the URL. SSRF protections still apply.
    allow_other_ytdlp_sites: bool = False

    # Tools
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    # JavaScript runtimes yt-dlp may use for YouTube (run sandboxed by yt-dlp): deno, node, bun, quickjs.
    ytdlp_js_runtimes: str = "deno,node"
    # "auto" picks libx264, then h264_videotoolbox, then mpeg4.
    ffmpeg_video_encoder: str = "auto"
    # Limit FFmpeg CPU threads (0 = FFmpeg decides). Keep low on a shared server.
    ffmpeg_threads: int = 0

    # Serve files through Nginx X-Accel-Redirect instead of streaming through Python.
    use_x_accel_redirect: bool = False
    x_accel_prefix: str = "/_protected_media"

    # Publishing (see docs/METRICOOL.md)
    publishing_provider: str = "none"  # "none" | "metricool"
    publishing_submit_enabled: bool = False
    publishing_accounts: list[dict] = Field(default_factory=list)
    metricool_user_token: str = ""
    metricool_user_id: str = ""
    metricool_blog_id: str = ""
    metricool_api_base: str = "https://app.metricool.com/api"

    @field_validator("supported_domains", "shortlink_hosts", mode="before")
    @classmethod
    def _split_csv(cls, v):
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("["):
                return json.loads(v)
            return [p.strip().lower() for p in v.split(",") if p.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def media_dir(self) -> Path:
        return (self.data_dir / "media").resolve()

    @property
    def work_dir(self) -> Path:
        return (self.data_dir / "work").resolve()

    @property
    def watermark_dir(self) -> Path:
        return (self.data_dir / "watermarks").resolve()

    @property
    def origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.allowed_origins.split(",") if o.strip()]

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.media_dir, self.work_dir, self.watermark_dir):
            d.mkdir(parents=True, exist_ok=True, mode=0o750)


@lru_cache
def get_settings() -> Settings:
    return Settings()
