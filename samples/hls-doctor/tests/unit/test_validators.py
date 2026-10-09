from hls_doctor.domain.playlist.parse_media_playlist import parse_media_playlist
from hls_doctor.domain.playlist.parse_multivariant import parse_multivariant
from hls_doctor.domain.playlist.tokenize_playlist import tokenize_playlist
from hls_doctor.domain.validate.validate_encryption import validate_encryption
from hls_doctor.domain.validate.validate_media_playlist import validate_media_playlist
from hls_doctor.domain.validate.validate_multivariant import validate_multivariant
from hls_doctor.domain.validate.validate_renditions import validate_renditions
from hls_doctor.domain.validate.validate_syntax import validate_syntax

URL = "https://demo.example/p.m3u8"


def titles(findings) -> list[str]:
    return [finding.title for finding in findings]


def test_missing_extm3u_is_fatal() -> None:
    findings = validate_syntax(URL, tokenize_playlist("#EXTINF:6.0,\ns.ts"))
    assert findings[0].severity.value == "FATAL"


def test_duplicate_unique_tag_is_an_error() -> None:
    lines = tokenize_playlist("#EXTM3U\n#EXT-X-VERSION:6\n#EXT-X-VERSION:7")
    assert "Duplicate EXT-X-VERSION tag" in titles(validate_syntax(URL, lines))


def test_variant_referencing_missing_group() -> None:
    playlist = parse_multivariant(
        tokenize_playlist('#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1,AUDIO="aud"\nv.m3u8')
    )
    assert "Variant references missing AUDIO group" in titles(validate_multivariant(URL, playlist))


def test_two_defaults_in_one_group() -> None:
    body = (
        "#EXTM3U\n"
        '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",NAME="en",DEFAULT=YES,URI="e.m3u8"\n'
        '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",NAME="es",DEFAULT=YES,URI="s.m3u8"\n'
    )
    playlist = parse_multivariant(tokenize_playlist(body))
    assert "Multiple DEFAULT=YES renditions in AUDIO group" in titles(
        validate_renditions(URL, playlist)
    )


def test_target_duration_violation() -> None:
    body = "#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXTINF:8.5,\ns.ts"
    playlist = parse_media_playlist(tokenize_playlist(body))
    assert "Segment duration exceeds EXT-X-TARGETDURATION" in titles(
        validate_media_playlist(URL, playlist)
    )


def test_encrypted_without_key_uri() -> None:
    body = "#EXTM3U\n#EXT-X-KEY:METHOD=AES-128\n#EXTINF:6.0,\ns.ts"
    playlist = parse_media_playlist(tokenize_playlist(body))
    assert "Encrypted segments without a key URI" in titles(validate_encryption(URL, playlist))
