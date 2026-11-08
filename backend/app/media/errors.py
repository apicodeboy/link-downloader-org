"""Convert raw yt-dlp / ffmpeg errors into clear messages for the user."""
from __future__ import annotations

import re


class MediaError(Exception):
    def __init__(self, code: str, message: str, detail: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail


class JobCancelled(MediaError):
    def __init__(self):
        super().__init__("cancelled", "Cancelled.")


_RULES: list[tuple[str, str, str]] = [
    (r"Blocked connection to non-public address|blocked_address", "blocked_address",
     "Blocked for security: the video host tried to send us to a private network address."),
    (r"Unsupported URL", "unsupported_url", "This link isn't a supported video page. Paste the post's direct link."),
    (r"DRM", "drm_protected", "This video is DRM-protected. DRM-protected content can't be downloaded."),
    (r"[Pp]rivate (video|account|post)|This (account|content) is private|is private", "private_content",
     "This content is private. Only public videos can be downloaded."),
    (r"(log ?in|sign ?in|logged.in|registered users|authentication|cookies).{0,80}(required|needed|to (view|access|confirm))"
     r"|requires? (a )?log ?in|use --cookies|Sign in to confirm", "login_required",
     "The platform requires a login to view this video. Login-protected content isn't supported."),
    (r"age.?(restricted|gate|verification)|inappropriate for some users", "age_restricted",
     "This video is age-restricted and needs a signed-in account, so it can't be downloaded."),
    (r"members.only|join this channel|paywall|purchase|premium", "paywalled",
     "This video is behind a membership or paywall and can't be downloaded."),
    (r"geo.?restrict|not available in your (country|location)|blocked it in your country", "geo_restricted",
     "This video isn't available from the server's country."),
    (r"HTTP Error 429|Too Many Requests|rate.?limit", "rate_limited",
     "The platform is rate-limiting the server. Wait a few minutes and try again."),
    (r"HTTP Error 404|not found|has been removed|no longer available|deleted|does not exist|Video unavailable",
     "not_found", "The video wasn't found. It may have been deleted or the link is wrong."),
    (r"No video (formats )?found|no video could be found|There's no video in this|Requested format is not available",
     "no_video", "No downloadable video was found in this post."),
    (r"live event|is_live|livestream|premiere", "live_content", "Live streams can't be downloaded while they're live."),
    (r"File is larger than max-filesize|exceeds size limit|max.filesize", "too_large",
     "The video is larger than the configured size limit."),
    (r"Unable to extract|Unable to download (JSON|webpage|API)", "extractor_failed",
     "The platform changed something and extraction failed. Try again later, or update yt-dlp."),
    (r"timed out|Read timed out|TimeoutError", "network_timeout", "The platform took too long to respond. Try again."),
    (r"Name or service not known|nodename nor servname|getaddrinfo|Temporary failure in name resolution", "dns_failed",
     "The server couldn't reach the platform (DNS lookup failed)."),
    (r"ffmpeg|ffprobe", "ffmpeg_failed", "FFmpeg could not process this video."),
]


def classify_error(raw: str) -> MediaError:
    text = raw or ""
    for pattern, code, message in _RULES:
        if re.search(pattern, text, re.IGNORECASE):
            return MediaError(code, message, text[-4000:])
    return MediaError("download_failed", "The download failed. See job details for the technical error.", text[-4000:])
