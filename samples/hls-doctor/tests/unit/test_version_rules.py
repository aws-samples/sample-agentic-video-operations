from hls_doctor.domain.playlist.parse_media_playlist import parse_media_playlist
from hls_doctor.domain.playlist.parse_multivariant import parse_multivariant
from hls_doctor.domain.playlist.tokenize_playlist import tokenize_playlist
from hls_doctor.domain.versioning.compute_required_version import (
    compute_version_findings,
    required_media_version,
    required_multivariant_version,
)


def media(body: str):
    return parse_media_playlist(tokenize_playlist("#EXTM3U\n" + body))


def test_daterange_and_gap_are_not_version_gated() -> None:
    # rfc8216bis §8 lists neither tag; flagging them was a confirmed false positive.
    daterange = media('#EXT-X-DATERANGE:ID="a",START-DATE="2026-01-01T00:00:00Z"')
    assert required_media_version(daterange) == (1, [])
    assert compute_version_findings("u", 4, *required_media_version(daterange)) == []
    assert required_media_version(media("#EXT-X-GAP\n#EXTINF:6,\ns.ts")) == (1, [])


def test_skip_requires_v9_and_removed_dateranges_v10() -> None:
    assert required_media_version(media("#EXT-X-SKIP:SKIPPED-SEGMENTS=3"))[0] == 9
    assert (
        required_media_version(
            media('#EXT-X-SKIP:SKIPPED-SEGMENTS=3,RECENTLY-REMOVED-DATERANGES="a"')
        )[0]
        == 10
    )


def test_fractional_extinf_requires_v3_and_sample_aes_v5() -> None:
    assert required_media_version(media("#EXTINF:5.96,\ns.ts"))[0] == 3
    assert required_media_version(media("#EXTINF:6,\ns.ts"))[0] == 1
    assert (
        required_media_version(media('#EXT-X-KEY:METHOD=SAMPLE-AES,URI="k"\n#EXTINF:6,\ns.ts'))[0]
        == 5
    )


def test_byterange_requires_v4_and_iv_v2() -> None:
    assert required_media_version(media("#EXT-X-BYTERANGE:100@0\n#EXTINF:6.0,\ns.ts"))[0] == 4
    assert (
        required_media_version(
            media('#EXT-X-KEY:METHOD=AES-128,URI="k",IV=0x01\n#EXTINF:6.0,\ns.ts')
        )[0]
        == 2
    )


def test_plain_playlist_requires_v1_and_no_finding() -> None:
    playlist = media("#EXTINF:6,\ns.ts")
    required, reasons = required_media_version(playlist)
    assert required == 1 and reasons == []
    assert compute_version_findings("u", None, required, reasons) == []


def test_declared_version_covering_features_passes() -> None:
    playlist = media('#EXT-X-MAP:URI="init.mp4"\n#EXTINF:6,\ns.m4s')
    required, reasons = required_media_version(playlist)
    assert required == 6
    assert compute_version_findings("u", 6, required, reasons) == []
    assert compute_version_findings("u", 3, required, reasons)[0].severity.value == "ERROR"


def test_multivariant_define_rules() -> None:
    plain = parse_multivariant(tokenize_playlist("#EXTM3U"))
    assert required_multivariant_version(plain)[0] == 1
    with_define = parse_multivariant(tokenize_playlist('#EXTM3U\n#EXT-X-DEFINE:NAME="a",VALUE="b"'))
    assert required_multivariant_version(with_define)[0] == 8
    with_queryparam = parse_multivariant(
        tokenize_playlist('#EXTM3U\n#EXT-X-DEFINE:QUERYPARAM="token"')
    )
    assert required_multivariant_version(with_queryparam)[0] == 11
