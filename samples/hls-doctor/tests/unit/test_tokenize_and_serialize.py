from hls_doctor.domain.playlist.serialize_playlist import serialize_playlist
from hls_doctor.domain.playlist.tokenize_playlist import tokenize_playlist

PLAYLIST = """#EXTM3U
#EXT-X-VERSION:7

# human comment
#EXT-X-VENDOR-SPECIAL:A=1,B="x,y"
#EXTINF:6.00000,Title text
seg0.m4s"""


def test_roundtrip_is_lossless() -> None:
    assert serialize_playlist(tokenize_playlist(PLAYLIST)) == PLAYLIST


def test_line_kinds_and_values() -> None:
    lines = tokenize_playlist(PLAYLIST)
    kinds = [line.kind for line in lines]
    assert kinds == ["tag", "tag", "blank", "comment", "tag", "tag", "uri"]
    assert lines[0].name == "EXTM3U" and lines[0].value is None
    assert lines[1].value == "7"
    assert lines[6].value == "seg0.m4s"


def test_unknown_tags_are_kept_and_marked() -> None:
    lines = tokenize_playlist(PLAYLIST)
    vendor = lines[4]
    assert vendor.name == "EXT-X-VENDOR-SPECIAL"
    assert not vendor.is_known_tag
    assert vendor.raw in serialize_playlist(lines)
