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


def test_daterange_requires_v7() -> None:
    playlist = media('#EXT-X-DATERANGE:ID="a",START-DATE="2026-01-01T00:00:00Z"')
    required, reasons = required_media_version(playlist)
    assert required == 7 and any("DATERANGE" in reason for reason in reasons)


def test_gap_requires_v8_and_skip_v9() -> None:
    assert required_media_version(media("#EXT-X-GAP\n#EXTINF:6.0,\ns.ts"))[0] == 8
    assert required_media_version(media("#EXT-X-SKIP:SKIPPED-SEGMENTS=3"))[0] == 9


def test_byterange_requires_v4_and_iv_v2() -> None:
    assert required_media_version(media("#EXT-X-BYTERANGE:100@0\n#EXTINF:6.0,\ns.ts"))[0] == 4
    assert (
        required_media_version(
            media('#EXT-X-KEY:METHOD=AES-128,URI="k",IV=0x01\n#EXTINF:6.0,\ns.ts')
        )[0]
        == 2
    )


def test_plain_playlist_requires_v1_and_no_finding() -> None:
    playlist = media("#EXTINF:6.0,\ns.ts")
    required, reasons = required_media_version(playlist)
    assert required == 1 and reasons == []
    assert compute_version_findings("u", None, required, reasons) == []


def test_declared_version_covering_features_passes() -> None:
    playlist = media('#EXT-X-DATERANGE:ID="a",START-DATE="2026-01-01T00:00:00Z"')
    required, reasons = required_media_version(playlist)
    assert compute_version_findings("u", 7, required, reasons) == []
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
