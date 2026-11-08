import json

from app.media.formats import BEST, build_format_options, selector_for, summarize_info
from tests.conftest import FIXTURES


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_twitter_formats_grouped_by_height():
    opts = build_format_options(load("twitter.json"))
    assert opts[0]["format_id"] == BEST
    heights = [o["height"] for o in opts[1:]]
    assert heights == [720, 360, 270]
    by_h = {o["height"]: o for o in opts[1:]}
    # Prefer the progressive H.264 HLS stream at 720p? No: http-2176 has unknown codecs but
    # includes audio, hls-2176 is video-only H.264. H.264 wins, and audio gets merged.
    assert by_h[720]["format_id"] == "hls-2176" and by_h[720]["needs_merge"] is True
    assert by_h[360]["format_id"] == "http-832" and by_h[360]["filesize"] == 1200000


def test_drm_and_storyboards_are_excluded():
    ids = [o["format_id"] for o in build_format_options(load("reddit.json"))]
    assert "hls-drm" not in ids and "sb0" not in ids
    assert ids == [BEST, "dash-480"]


def test_size_estimate_includes_audio_for_video_only():
    opts = build_format_options(load("youtube_short.json"))
    top = opts[1]
    assert top["format_id"] == "137"  # H.264 preferred over VP9 at the same height
    assert top["filesize"] == 8_500_000
    assert top["has_audio"] is True


def test_selectors():
    assert selector_for({"format_id": BEST}) == "bv*+ba/b"
    assert selector_for({"format_id": "137", "height": 1920, "needs_merge": True}) == \
        "137+ba[ext=m4a]/137+ba/bv*[height<=1920]+ba/b[height<=1920]"
    assert selector_for({"format_id": "18", "height": 640, "needs_merge": False}) == \
        "18/bv*[height<=640]+ba/b[height<=640]"


def test_summary_is_json_safe_and_complete():
    s = summarize_info(load("youtube_short.json"))
    json.dumps(s)
    assert s["duration"] == 31.0 and s["platform"] == "youtube" and s["caption_available"]
    assert s["formats"][0]["format_id"] == BEST
