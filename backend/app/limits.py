"""Per-role limits: guests get modest limits, admins (the site owner) get the full ones."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from .config import Settings, get_settings


@dataclass(frozen=True)
class Limits:
    max_filesize_mb: int
    max_duration_seconds: int
    process_max_duration_seconds: int | None  # None = no extra limit
    max_pending_jobs: int
    retention_minutes: int
    priority: bool

    def as_dict(self) -> dict:
        return asdict(self)


def limits_for(role: str | None, settings: Settings | None = None) -> Limits:
    s = settings or get_settings()
    if role == "admin":
        return Limits(
            max_filesize_mb=s.max_filesize_mb,
            max_duration_seconds=s.max_duration_seconds,
            process_max_duration_seconds=None,
            max_pending_jobs=s.max_pending_jobs_per_user,
            retention_minutes=max(s.retention_minutes, s.admin_retention_minutes),
            priority=True,
        )
    return Limits(
        max_filesize_mb=min(s.guest_max_filesize_mb, s.max_filesize_mb),
        max_duration_seconds=min(s.guest_max_duration_seconds, s.max_duration_seconds),
        process_max_duration_seconds=s.guest_process_max_duration_seconds,
        max_pending_jobs=min(s.guest_max_pending_jobs, s.max_pending_jobs_per_user),
        retention_minutes=s.retention_minutes,
        priority=False,
    )
