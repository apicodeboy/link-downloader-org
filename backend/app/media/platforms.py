"""Map yt-dlp extractor keys to the platforms the UI knows about."""
from __future__ import annotations

_PLATFORM_PREFIXES = {
    "twitter": "twitter",
    "instagram": "instagram",
    "facebook": "facebook",
    "tiktok": "tiktok",
    "vm.tiktok": "tiktok",
    "youtube": "youtube",
    "reddit": "reddit",
}

PLATFORM_LABELS = {
    "twitter": "X / Twitter",
    "instagram": "Instagram",
    "facebook": "Facebook",
    "tiktok": "TikTok",
    "youtube": "YouTube",
    "reddit": "Reddit",
    "other": "Other",
}


def platform_from_extractor(extractor_key: str | None) -> str:
    key = (extractor_key or "").lower()
    for prefix, platform in _PLATFORM_PREFIXES.items():
        if key.startswith(prefix):
            return platform
    return "other"
