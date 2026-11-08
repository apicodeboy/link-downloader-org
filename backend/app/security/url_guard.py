"""Strict validation of user-supplied video URLs (SSRF protection, layer 1 and 2).

Layer 1 (`validate_url`) is static: scheme, credentials, port, hostname shape, allowlist.
Layer 2 (`check_dns`, `resolve_redirects`) resolves DNS and refuses any non-public address.
Redirects are followed one hop at a time, re-validating every hop, and each request is
pinned to the IP address we already checked, so a DNS answer cannot change between the
check and the connection (DNS rebinding).
Layer 3 lives in `net_guard` and protects connections made by yt-dlp itself.
"""
from __future__ import annotations

import ipaddress
import re
import socket
import ssl
from functools import lru_cache
from urllib.parse import urljoin, urlsplit, urlunsplit

import certifi
import urllib3

from ..config import Settings, get_settings
from .ip_policy import is_public_ip

MAX_URL_LENGTH = 2048
MAX_REDIRECTS = 5
_BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal", ".arpa", ".lan", ".home", ".corp", ".intranet")
_BLOCKED_HOSTS = {"localhost", "metadata", "metadata.google.internal", "instance-data"}
_USER_AGENT = "Mozilla/5.0 (compatible; VideoDownloader/1.0; link-expander)"


class URLRejected(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def host_matches(host: str, domains: list[str]) -> bool:
    host = host.lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in domains)


@lru_cache(maxsize=1)
def _dedicated_extractors():
    from yt_dlp.extractor import gen_extractor_classes

    return [ie for ie in gen_extractor_classes() if ie.ie_key() != "Generic"]


def has_dedicated_extractor(url: str) -> bool:
    """True if a site-specific yt-dlp extractor (not the generic page scraper) handles url."""
    return any(ie.suitable(url) and ie.working() for ie in _dedicated_extractors())


def validate_url(raw: str, settings: Settings | None = None) -> str:
    """Return a normalized URL or raise URLRejected. Performs no network access."""
    settings = settings or get_settings()
    if not isinstance(raw, str):
        raise URLRejected("invalid_url", "URL must be text.")
    url = raw.strip()
    if not url:
        raise URLRejected("invalid_url", "Please paste a video URL.")
    if len(url) > MAX_URL_LENGTH:
        raise URLRejected("invalid_url", "That URL is too long.")
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url):
        raise URLRejected("invalid_url", "URLs cannot contain spaces or control characters.")
    if "://" not in url:
        scheme_like = re.match(r"^([A-Za-z][A-Za-z0-9+.-]*):(?!\d)", url)
        if scheme_like:
            raise URLRejected("invalid_scheme", "Only http:// and https:// links are allowed.")
        url = "https://" + url

    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise URLRejected("invalid_scheme", "Only http:// and https:// links are allowed.")
    if "@" in parts.netloc or parts.username or parts.password:
        raise URLRejected("invalid_url", "URLs with embedded usernames or passwords are not allowed.")
    if "\\" in url:
        raise URLRejected("invalid_url", "Backslashes are not allowed in URLs.")
    try:
        port = parts.port
    except ValueError:
        raise URLRejected("invalid_url", "The URL has an invalid port.") from None
    if port not in (None, 80, 443):
        raise URLRejected("invalid_port", "Only standard web ports (80 and 443) are allowed.")

    host = (parts.hostname or "").rstrip(".")
    if not host:
        raise URLRejected("invalid_url", "The URL has no host name.")
    try:
        host = host.encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise URLRejected("invalid_url", "The URL has an invalid host name.") from None

    try:
        ipaddress.ip_address(host.strip("[]"))
        is_ip = True
    except ValueError:
        is_ip = False
    if is_ip or host.replace(".", "").isdigit() or host.startswith("0x"):
        raise URLRejected("ip_literal", "Links to raw IP addresses are not allowed.")
    if "." not in host or host in _BLOCKED_HOSTS or host.endswith(_BLOCKED_HOST_SUFFIXES):
        raise URLRejected("blocked_host", "That host is not allowed.")
    if host.startswith("metadata."):
        raise URLRejected("blocked_host", "That host is not allowed.")

    netloc = host if port in (None, 443 if scheme == "https" else 80) else f"{host}:{port}"
    normalized = urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))

    if not host_matches(host, settings.supported_domains):
        if not (settings.allow_other_ytdlp_sites and has_dedicated_extractor(normalized)):
            raise URLRejected(
                "unsupported_site",
                f"{host} is not a supported site. Supported: X/Twitter, Instagram, Facebook, "
                "TikTok, YouTube, and Reddit.",
            )
    return normalized


def check_dns(host: str, port: int = 443) -> list[str]:
    """Resolve host and require every address to be public. Returns the addresses."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise URLRejected("dns_failed", f"Could not resolve {host}. Check the link.") from None
    addrs: list[str] = []
    for family, *_rest, sockaddr in infos:
        ip = sockaddr[0]
        if not is_public_ip(ip):
            raise URLRejected(
                "blocked_address",
                "Blocked for security: that link points to a private or internal network address.",
            )
        if ip not in addrs:
            addrs.append(ip)
    if not addrs:
        raise URLRejected("dns_failed", f"Could not resolve {host}.")
    # Prefer IPv4: simpler for the pinned connection and works on IPv4-only VPS networks.
    addrs.sort(key=lambda a: ":" in a)
    return addrs


def _pinned_request(url: str, ip: str, method: str, timeout: float) -> tuple[int, str | None]:
    parts = urlsplit(url)
    host = parts.hostname or ""
    port = parts.port or (443 if parts.scheme == "https" else 80)
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    tmo = urllib3.Timeout(connect=timeout, read=timeout)
    if parts.scheme == "https":
        ctx = ssl.create_default_context(cafile=certifi.where())
        pool = urllib3.HTTPSConnectionPool(
            ip, port=port, server_hostname=host, assert_hostname=host,
            ssl_context=ctx, timeout=tmo, retries=False, maxsize=1,
        )
    else:
        pool = urllib3.HTTPConnectionPool(ip, port=port, timeout=tmo, retries=False, maxsize=1)
    try:
        resp = pool.request(
            method, path,
            headers={"Host": parts.netloc, "User-Agent": _USER_AGENT, "Accept": "*/*"},
            redirect=False, preload_content=False,
        )
        status, location = resp.status, resp.headers.get("Location")
        resp.release_conn()
        return status, location
    except urllib3.exceptions.HTTPError as exc:
        raise URLRejected("redirect_failed", f"Could not open the short link ({type(exc).__name__}).") from None
    finally:
        pool.close()


def resolve_redirects(url: str, settings: Settings | None = None, timeout: float = 10.0) -> str:
    """Expand known short links (t.co, vm.tiktok.com, ...) safely and return the final URL.

    Each hop is re-validated against the allowlist and DNS policy, and the request goes to
    the exact IP that passed the check. Non-shortlink URLs are returned unchanged
    (after validation); yt-dlp handles platform redirects behind the socket guard.
    """
    settings = settings or get_settings()
    for _ in range(MAX_REDIRECTS + 1):
        url = validate_url(url, settings)
        parts = urlsplit(url)
        host = parts.hostname or ""
        if not host_matches(host, settings.shortlink_hosts):
            return url
        ip = check_dns(host, parts.port or 443)[0]
        status, location = _pinned_request(url, ip, "HEAD", timeout)
        if status in (405, 403, 400):
            status, location = _pinned_request(url, ip, "GET", timeout)
        if status in (301, 302, 303, 307, 308) and location:
            url = urljoin(url, location)
            continue
        if status >= 400:
            raise URLRejected("redirect_failed", f"The short link returned HTTP {status}.")
        return url
    raise URLRejected("too_many_redirects", "The link redirects too many times.")
