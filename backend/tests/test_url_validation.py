import pytest

from app.security.url_guard import URLRejected, validate_url


@pytest.mark.parametrize("url", [
    "https://x.com/someone/status/1234567890",
    "https://twitter.com/someone/status/1234567890",
    "https://www.instagram.com/reel/AbC123/",
    "https://www.facebook.com/reel/1234567890",
    "https://fb.watch/abcd/",
    "https://www.tiktok.com/@user/video/1234567890",
    "https://vm.tiktok.com/ZMabc/",
    "https://www.youtube.com/shorts/abcdefghijk",
    "https://youtu.be/abcdefghijk",
    "https://www.reddit.com/r/videos/comments/abc/title/",
    "https://v.redd.it/abc123",
    "http://www.youtube.com/shorts/abcdefghijk",
])
def test_accepts_supported_platforms(settings, url):
    assert validate_url(url, settings).startswith(("https://", "http://"))


def test_adds_scheme_and_normalizes(settings):
    assert validate_url("  WWW.YouTube.com/shorts/abc  ", settings) == "https://www.youtube.com/shorts/abc"
    assert validate_url("https://x.com:443/a#frag", settings) == "https://x.com/a"


@pytest.mark.parametrize("url,code", [
    ("ftp://x.com/video", "invalid_scheme"),
    ("file:///etc/passwd", "invalid_scheme"),
    ("javascript:alert(1)", "invalid_scheme"),
    ("gopher://x.com/", "invalid_scheme"),
    ("https://user:pass@x.com/a", "invalid_url"),
    ("https://x.com@evil.example/a", "invalid_url"),
    ("https://x.com:8080/a", "invalid_port"),
    ("https://x.com:22/a", "invalid_port"),
    ("https://127.0.0.1/a", "ip_literal"),
    ("https://[::1]/a", "ip_literal"),
    ("https://169.254.169.254/latest/meta-data/", "ip_literal"),
    ("https://2130706433/", "ip_literal"),
    ("https://0x7f000001/", "ip_literal"),
    ("https://localhost/a", "blocked_host"),
    ("https://metadata.google.internal/computeMetadata/v1/", "blocked_host"),
    ("https://foo.internal/", "blocked_host"),
    ("https://example.com/video.mp4", "unsupported_site"),
    ("https://evilinstagram.com/reel/1", "unsupported_site"),
    ("https://instagram.com.evil.example/reel/1", "unsupported_site"),
    ("https://x.com/a b", "invalid_url"),
    ("https://x.com/a\nb", "invalid_url"),
    ("https://x.com\\@evil.example/", "invalid_url"),
    ("", "invalid_url"),
    ("https://x.com/" + "a" * 3000, "invalid_url"),
])
def test_rejects_unsafe_or_unsupported(settings, url, code):
    with pytest.raises(URLRejected) as exc:
        validate_url(url, settings)
    assert exc.value.code == code


def test_other_ytdlp_sites_need_dedicated_extractor(settings):
    with pytest.raises(URLRejected):
        validate_url("https://vimeo.com/76979871", settings)
    settings.allow_other_ytdlp_sites = True
    assert validate_url("https://vimeo.com/76979871", settings) == "https://vimeo.com/76979871"
    # The generic extractor never counts, so arbitrary sites stay blocked.
    with pytest.raises(URLRejected) as exc:
        validate_url("https://example.com/some/page", settings)
    assert exc.value.code == "unsupported_site"
