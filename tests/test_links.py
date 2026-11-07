import pytest

from bot.links import canonical_key, find_links, from_payload, parse, to_payload


@pytest.mark.parametrize("raw, key, url", [
    ("https://www.tiktok.com/@user/video/123", "tt:123", "https://www.tiktok.com/@user/video/123"),
    ("tiktok.com/@user/photo/123?lang=en", "tt:123", "https://www.tiktok.com/@user/video/123"),
    ("https://m.tiktok.com/v/video/456.", "tt:456", "https://www.tiktok.com/@/video/456"),
    ("https://vm.tiktok.com/ZMabc12/", "tt-short:ZMabc12", "https://vm.tiktok.com/ZMabc12/"),
    ("https://www.tiktok.com/t/ZTxyz/", "tt-short:ZTxyz", "https://www.tiktok.com/t/ZTxyz/"),
    ("https://www.instagram.com/reels/C0de_1/?igsh=x", "ig:C0de_1", "https://www.instagram.com/reel/C0de_1/"),
    ("instagram.com/p/AbC/", "ig:AbC", "https://www.instagram.com/p/AbC/"),
    ("https://www.instagram.com/share/reel/BAx1/", "ig-share:BAx1", "https://www.instagram.com/share/reel/BAx1/"),
    ("https://youtube.com/shorts/FFK9hSYmEu0?si=1", "yt:FFK9hSYmEu0", "https://www.youtube.com/watch?v=FFK9hSYmEu0"),
    ("https://youtu.be/FFK9hSYmEu0", "yt:FFK9hSYmEu0", "https://www.youtube.com/watch?v=FFK9hSYmEu0"),
    ("https://m.youtube.com/watch?v=FFK9hSYmEu0&t=3", "yt:FFK9hSYmEu0", "https://www.youtube.com/watch?v=FFK9hSYmEu0"),
])
def test_parse(raw, key, url):
    link = parse(raw)
    assert (link.key, link.url) == (key, url)


@pytest.mark.parametrize("raw", [
    "https://www.tiktok.com/@user", "https://www.instagram.com/someone/", "https://youtube.com/@channel",
    "https://youtube.com/watch?v=short", "https://example.com/video/1",
])
def test_parse_rejects_non_posts(raw):
    assert parse(raw) is None


def test_find_links_dedupes_spellings_of_one_post():
    text = "look https://www.tiktok.com/@a/video/1 and tiktok.com/@b/photo/1, also youtu.be/FFK9hSYmEu0!"
    assert [link.key for link in find_links(text)] == ["tt:1", "yt:FFK9hSYmEu0"]


def test_short_links_expand_to_posts():
    assert parse("https://vm.tiktok.com/ZMabc12/").expands_to == "tt:"
    assert parse("https://www.instagram.com/share/p/X1/").expands_to == "ig:"
    assert parse("https://www.tiktok.com/@a/video/1").expands_to is None


def test_payload_round_trip():
    assert to_payload("tt:123") == "tt_123"
    assert from_payload("tt_123").key == "tt:123"
    assert from_payload("ig_AbC-1").key == "ig:AbC-1"
    assert to_payload("yt:FFK9hSYmEu0") is None
    assert from_payload("help") is None


def test_canonical_key_skips_short_and_extractor_keys():
    assert canonical_key(["tt-short:x", "tiktok:1", "tt:1"]) == "tt:1"
    assert canonical_key(["yt:FFK9hSYmEu0"]) is None
