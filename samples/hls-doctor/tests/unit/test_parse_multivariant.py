from hls_doctor.domain.playlist.parse_multivariant import parse_multivariant
from hls_doctor.domain.playlist.tokenize_playlist import tokenize_playlist

PLAYLIST = """#EXTM3U
#EXT-X-VERSION:8
#EXT-X-DEFINE:NAME="cdn",VALUE="edge-1"
#EXT-X-CONTENT-STEERING:SERVER-URI="steering.json",PATHWAY-ID="A"
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",NAME="English",LANGUAGE="en",DEFAULT=YES,URI="a/en.m3u8"
#EXT-X-MEDIA:TYPE=CLOSED-CAPTIONS,GROUP-ID="cc",NAME="CC1",INSTREAM-ID="CC1"
#EXT-X-STREAM-INF:BANDWIDTH=2000000,RESOLUTION=1280x720,FRAME-RATE=29.970,AUDIO="aud"
v720.m3u8
#EXT-X-I-FRAME-STREAM-INF:BANDWIDTH=90000,URI="iframe.m3u8"
#EXT-X-SESSION-KEY:METHOD=AES-128,URI="key.bin"
"""


def test_variants_renditions_and_iframe() -> None:
    playlist = parse_multivariant(tokenize_playlist(PLAYLIST))
    assert [variant.uri for variant in playlist.variants] == ["v720.m3u8", "iframe.m3u8"]
    assert playlist.variants[0].resolution == (1280, 720)
    assert playlist.variants[1].iframe_only
    assert playlist.renditions[0].default and playlist.renditions[0].language == "en"
    assert playlist.renditions[1].instream_id == "CC1"


def test_steering_defines_and_session_keys() -> None:
    playlist = parse_multivariant(tokenize_playlist(PLAYLIST))
    assert playlist.steering is not None and playlist.steering.pathway_id == "A"
    assert playlist.defines[0].name == "cdn" and playlist.defines[0].value == "edge-1"
    assert playlist.session_keys[0].uri == "key.bin"
    assert playlist.version == 8
