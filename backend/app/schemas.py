"""Request bodies."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class AnalyzeIn(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class DownloadIn(BaseModel):
    analysis_job_id: str = Field(min_length=1, max_length=32)
    format_id: str = Field(default="best", min_length=1, max_length=128)


class ProcessOptions(BaseModel):
    aspect: Literal["original", "9:16"] = "original"
    fill_mode: Literal["blur", "black"] = "blur"
    watermark_file_id: str | None = Field(default=None, max_length=32)
    watermark_size_pct: float = Field(default=15.0, ge=2, le=50)
    watermark_opacity: float = Field(default=0.8, ge=0.05, le=1.0)
    watermark_margin_pct: float = Field(default=3.0, ge=0, le=20)
    thumbnails: bool = False


class ProcessIn(ProcessOptions):
    preset_id: int | None = None


class PresetIn(ProcessOptions):
    name: str = Field(min_length=1, max_length=100)


def normalize_hashtags(tags: list[str]) -> list[str]:
    out: list[str] = []
    for t in tags:
        t = t.strip()
        if not t:
            continue
        t = "#" + t.lstrip("#")
        if len(t) > 100 or any(c.isspace() for c in t):
            raise ValueError(f"Invalid hashtag: {t[:30]}")
        if t not in out:
            out.append(t)
    return out


class PublishingJobIn(BaseModel):
    media_file_id: str = Field(min_length=1, max_length=32)
    caption: str = Field(default="", max_length=5000)
    hashtags: list[str] = Field(default_factory=list, max_length=30)
    destinations: list[str] = Field(default_factory=list, max_length=20)
    scheduled_at: datetime | None = None

    @field_validator("hashtags")
    @classmethod
    def _norm_tags(cls, tags: list[str]) -> list[str]:
        return normalize_hashtags(tags)


class PublishingJobUpdate(BaseModel):
    caption: str | None = Field(default=None, max_length=5000)
    hashtags: list[str] | None = Field(default=None, max_length=30)
    destinations: list[str] | None = Field(default=None, max_length=20)
    scheduled_at: datetime | None = None

    @field_validator("hashtags")
    @classmethod
    def _norm_tags(cls, tags: list[str] | None) -> list[str] | None:
        return None if tags is None else normalize_hashtags(tags)
