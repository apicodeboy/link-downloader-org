import json

from app.media.captions import extract_caption, extract_hashtags
from tests.conftest import FIXTURES


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_twitter_caption_is_post_text_exactly():
    info = load("twitter.json")
    cap = extract_caption(info)
    assert cap["platform"] == "twitter"
    assert cap["caption"] == info["description"]  # byte-for-byte, incl. emoji ZWJ and blank line
    assert "\n\n" in cap["caption"] and "👩‍👩‍👧" in cap["caption"] and "—" in cap["caption"]
    assert cap["caption_source"] == "post_text"
    assert cap["title_is_generated"] is True
    assert cap["hashtags"] == ["#sunrise", "#Café", "#日本"]
    assert cap["creator"] == {"name": "Jane Doe", "handle": "janedoe", "url": "https://twitter.com/janedoe"}


def test_missing_caption_is_not_invented():
    cap = extract_caption(load("instagram_no_caption.json"))
    assert cap["caption"] is None
    assert cap["caption_available"] is False
    assert cap["title"] == "Video by someuser" and cap["title_is_generated"] is True
    assert cap["hashtags"] == []


def test_reddit_uses_post_title():
    cap = extract_caption(load("reddit.json"))
    assert cap["caption"] == "My cat learned to open doors 😼 (sound on)"
    assert cap["caption_source"] == "post_title"


def test_youtube_uses_description_and_keeps_tags_separate():
    cap = extract_caption(load("youtube_short.json"))
    assert cap["caption_source"] == "video_description"
    assert cap["caption"].startswith("Full tutorial on my channel!\nMusic")
    assert cap["hashtags"] == ["#lifehack", "#laundry"]
    assert cap["tags"] == ["laundry", "lifehack"]
    assert cap["title_is_generated"] is False


def test_whitespace_only_description_counts_as_missing():
    cap = extract_caption({"extractor_key": "TikTok", "title": "x", "description": "  \n "})
    assert cap["caption"] is None


def test_caption_whitespace_is_preserved():
    text = "  line one\r\nline two  \n"
    assert extract_caption({"extractor_key": "Instagram", "description": text})["caption"] == text


def test_hashtag_parsing_edge_cases():
    text = "#one two#notatag &#123; #مرحبا #ok_2 #ONE #123 #_under (#paren) #tag.end"
    assert extract_hashtags(text) == ["#one", "#مرحبا", "#ok_2", "#_under", "#paren", "#tag"]
