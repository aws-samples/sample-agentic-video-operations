from hls_doctor.domain.playlist.parse_media_playlist import parse_media_playlist
from hls_doctor.domain.playlist.tokenize_playlist import tokenize_playlist

PLAYLIST = """#EXTM3U
#EXT-X-VERSION:9
#EXT-X-TARGETDURATION:6
#EXT-X-MEDIA-SEQUENCE:100
#EXT-X-SKIP:SKIPPED-SEGMENTS=2
#EXT-X-MAP:URI="init.mp4"
#EXT-X-KEY:METHOD=AES-128,URI="k1.bin"
#EXTINF:6.0,
seg102.m4s
#EXT-X-KEY:METHOD=AES-128,URI="k2.bin"
#EXT-X-DISCONTINUITY
#EXT-X-CUE-OUT:30
#EXTINF:5.5,
seg103.m4s
#EXT-X-PART:DURATION=1.0,URI="seg104.part0.m4s",INDEPENDENT=YES
#EXT-X-PRELOAD-HINT:TYPE=PART,URI="seg104.part1.m4s"
#EXT-X-RENDITION-REPORT:URI="../v720/prog.m3u8",LAST-MSN=103,LAST-PART=0
"""


def parsed():
    return parse_media_playlist(tokenize_playlist(PLAYLIST))


def test_media_sequence_numbers_include_skip() -> None:
    media = parsed()
    assert [segment.media_sequence_number for segment in media.segments] == [102, 103]


def test_key_and_map_persist_until_replaced() -> None:
    media = parsed()
    first, second = media.segments
    assert first.key is not None and first.key.uri == "k1.bin"
    assert second.key is not None and second.key.uri == "k2.bin"
    assert first.segment_map is not None and second.segment_map is not None
    assert second.segment_map.uri == "init.mp4"


def test_discontinuity_and_cue_lines_attach_to_the_next_segment() -> None:
    media = parsed()
    assert not media.segments[0].discontinuity
    assert media.segments[1].discontinuity
    assert media.segments[1].cue_lines  # the EXT-X-CUE-OUT line


def test_trailing_parts_and_ll_hls_tags() -> None:
    media = parsed()
    assert [part.uri for part in media.trailing_parts] == ["seg104.part0.m4s"]
    assert media.preload_hints[0].uri == "seg104.part1.m4s"
    assert media.rendition_reports[0].last_msn == 103
    assert media.skip is not None and media.skip.skipped_segments == 2
