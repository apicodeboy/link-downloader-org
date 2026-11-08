"""Publishing providers.

A provider turns an approved PublishingJob into a post on an external service. Only
behaviour that has been verified against the provider's official documentation is
implemented; everything else raises ProviderNotReady with an explanation.

Verified for Metricool (https://help.metricool.com/basic-guide-for-api-integration-r97af):
* API access requires an Advanced or Custom plan.
* Base URL https://app.metricool.com/api, header `X-Mc-Auth: <token>`, and `userId` +
  `blogId` query parameters.
* `GET /admin/simpleProfiles?userId=...` lists brands.
* `POST /v2/scheduler/posts` creates a scheduled post (publicationDate, text, providers).
* Media must be at a PUBLIC, NON-EXPIRING URL and normalized first; otherwise the post is
  scheduled WITHOUT media.

NOT verified (so not implemented): the video upload flow. This app intentionally keeps
media private and deletes it after the retention period, which conflicts with Metricool's
public, non-expiring media URL requirement. See docs/METRICOOL.md.
"""
from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

import certifi

from ..config import Settings, get_settings
from ..models import PublishingJob


class ProviderNotReady(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Destination:
    id: str
    network: str
    label: str


class PublishingProvider(Protocol):
    name: str

    def configured(self) -> bool: ...
    def destinations(self) -> list[Destination]: ...
    def check_connection(self) -> dict[str, Any]: ...
    def submit(self, job: PublishingJob, media_url: str | None) -> dict[str, Any]: ...


def _configured_destinations(settings: Settings) -> list[Destination]:
    out = []
    for item in settings.publishing_accounts:
        if isinstance(item, dict) and item.get("id") and item.get("network"):
            out.append(Destination(str(item["id"]), str(item["network"]).lower(),
                                   str(item.get("label") or item["id"])))
    return out


class NoProvider:
    """Default: prepare jobs and export a publish package (MP4 + caption) for manual upload."""

    name = "none"

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def configured(self) -> bool:
        return False

    def destinations(self) -> list[Destination]:
        return _configured_destinations(self.settings)

    def check_connection(self) -> dict[str, Any]:
        return {"ok": False, "message": "No publishing provider is configured (PUBLISHING_PROVIDER=none)."}

    def submit(self, job: PublishingJob, media_url: str | None) -> dict[str, Any]:
        raise ProviderNotReady("no_provider", "No publishing provider is configured. Download the publish "
                                              "package and upload it manually.")


class MetricoolProvider:
    name = "metricool"

    def __init__(self, settings: Settings | None = None, opener=None):
        self.settings = settings or get_settings()
        self._opener = opener or self._default_open

    def configured(self) -> bool:
        s = self.settings
        return bool(s.metricool_user_token and s.metricool_user_id and s.metricool_blog_id)

    def destinations(self) -> list[Destination]:
        return _configured_destinations(self.settings)

    @staticmethod
    def _default_open(req: urllib.request.Request, timeout: float):
        ctx = ssl.create_default_context(cafile=certifi.where())
        return urllib.request.urlopen(req, timeout=timeout, context=ctx)  # noqa: S310 - fixed https host

    def _get(self, path: str, params: dict[str, str]) -> Any:
        s = self.settings
        base = s.metricool_api_base.rstrip("/")
        if not base.startswith("https://app.metricool.com/"):
            raise ProviderNotReady("bad_config", "METRICOOL_API_BASE must be https://app.metricool.com/api.")
        url = f"{base}{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"X-Mc-Auth": s.metricool_user_token, "Accept": "application/json"})
        with self._opener(req, 15) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def check_connection(self) -> dict[str, Any]:
        """Read-only call to the documented brand-list endpoint. Never posts anything."""
        if not self.configured():
            return {"ok": False, "message": "Set METRICOOL_USER_TOKEN, METRICOOL_USER_ID and METRICOOL_BLOG_ID."}
        try:
            data = self._get("/admin/simpleProfiles", {"userId": self.settings.metricool_user_id})
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": f"Metricool request failed: {type(exc).__name__}: {str(exc)[:200]}"}
        brands = data if isinstance(data, list) else data.get("data", []) if isinstance(data, dict) else []
        names = [str(b.get("label") or b.get("title") or b.get("id")) for b in brands if isinstance(b, dict)]
        return {"ok": True, "message": f"Connected. {len(names)} brand(s) visible.", "brands": names[:20]}

    def submit(self, job: PublishingJob, media_url: str | None) -> dict[str, Any]:
        raise ProviderNotReady(
            "not_verified",
            "Automatic video publishing to Metricool is not enabled. Metricool requires media at a public, "
            "non-expiring URL, and its video upload flow has not been verified for this app. Download the "
            "publish package and upload it in Metricool, or see docs/METRICOOL.md to finish the integration.",
        )


def get_provider(settings: Settings | None = None) -> PublishingProvider:
    s = settings or get_settings()
    if s.publishing_provider == "metricool":
        return MetricoolProvider(s)
    return NoProvider(s)
