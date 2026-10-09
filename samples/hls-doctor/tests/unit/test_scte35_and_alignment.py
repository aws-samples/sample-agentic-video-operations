import pytest

from hls_doctor.domain.align.compare_renditions import compare_renditions
from hls_doctor.domain.align.match_rendition_positions import read_position
from hls_doctor.domain.playlist.parse_media_playlist import parse_media_playlist
from hls_doctor.domain.playlist.tokenize_playlist import tokenize_playlist
from hls_doctor.domain.scte35.collect_ad_breaks import collect_ad_breaks, validate_ad_breaks
from hls_doctor.domain.scte35.decode_splice_info import decode_splice_info
from media_ops_contracts.tool_failure import ToolFailure

# Published splice_insert sample: event 1207959695, out-of-network, 60.294 s break.
SPLICE_INSERT = "/DAvAAAAAAAA///wFAVIAACPf+/+c2nALv4AUsz1AAAAAAAKAAhDVUVJAAABNWLbowo="
# Published time_signal sample with one segmentation descriptor (type 0x34, 307 s).
TIME_SIGNAL = "/DA0AAAAAAAA///wBQb+cr0AUAAeAhxDVUVJSAAAjn/PAAGlmbAICAAAAAAsoKGKNAIAmsnRfg=="


def test_decodes_a_published_splice_insert() -> None:
    section = decode_splice_info(SPLICE_INSERT)
    insert = section.splice_insert
    assert section.command_name == "splice_insert" and insert is not None
    assert insert.event_id == 1207959695 and insert.out_of_network is True
    assert insert.break_duration_seconds == pytest.approx(60.294, abs=0.001)
    assert insert.auto_return is True


def test_decodes_a_published_time_signal_with_descriptor() -> None:
    section = decode_splice_info(TIME_SIGNAL)
    assert section.command_name == "time_signal"
    [descriptor] = section.segmentation_descriptors
    assert descriptor.type_id == 0x34
    assert descriptor.type_name == "Provider Placement Opportunity Start"
    assert descriptor.duration_seconds == pytest.approx(307.0, abs=0.01)


def test_hex_payloads_decode_and_garbage_is_a_tool_failure() -> None:
    import base64

    as_hex = "0x" + base64.b64decode(SPLICE_INSERT).hex()
    assert decode_splice_info(as_hex).command_name == "splice_insert"
    with pytest.raises(ToolFailure):
        decode_splice_info("not-a-payload!!!")
    with pytest.raises(ToolFailure):
        decode_splice_info("0xdeadbeef")  # wrong table id / truncated


def media_with(lines_text: str):
    lines = tokenize_playlist("#EXTM3U\n#EXT-X-TARGETDURATION:6\n" + lines_text)
    return lines, parse_media_playlist(lines)


def test_cue_out_without_cue_in_is_flagged() -> None:
    lines, media = media_with("#EXT-X-CUE-OUT:DURATION=30.0\n#EXTINF:6.0,\ns.ts")
    findings = validate_ad_breaks("u", collect_ad_breaks(lines, media))
    assert findings[0].title == "Ad break opened without a matching CUE-IN"


def test_daterange_duration_mismatch_against_decoded_payload() -> None:
    import base64

    payload = "0x" + base64.b64decode(SPLICE_INSERT).hex()
    lines, media = media_with(
        '#EXT-X-DATERANGE:ID="b1",START-DATE="2026-10-06T14:00:00Z",'
        f'END-DATE="2026-10-06T14:00:30Z",DURATION=30.0,SCTE35-OUT={payload}\n'
        "#EXTINF:6.0,\ns.ts"
    )
    titles = [f.title for f in validate_ad_breaks("u", collect_ad_breaks(lines, media))]
    assert "Ad break duration disagrees with its SCTE-35 payload" in titles


def position(url: str, role: str, body: str):
    return read_position(url, role, parse_media_playlist(tokenize_playlist(body)))


def test_audio_drift_is_detected_at_a_shared_msn() -> None:
    video = position(
        "v",
        "video",
        "#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:10\n"
        "#EXT-X-PROGRAM-DATE-TIME:2026-10-06T14:00:00.000Z\n#EXTINF:6.0,\na.ts\n",
    )
    audio = position(
        "a",
        "audio",
        "#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:10\n"
        "#EXT-X-PROGRAM-DATE-TIME:2026-10-06T13:59:57.900Z\n#EXTINF:6.0,\na.ts\n",
    )
    [finding] = compare_renditions([video, audio])
    assert finding.title == "Audio rendition drifts from video"
    assert "2.1 s behind" in finding.observations[0].statement


def test_variant_lag_requires_two_segments() -> None:
    ahead = position("v1", "video", "#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:12\n#EXTINF:6.0,\na.ts\n")
    close = position("v2", "video", "#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:11\n#EXTINF:6.0,\na.ts\n")
    behind = position("v3", "video", "#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:9\n#EXTINF:6.0,\na.ts\n")
    titles = [f.title for f in compare_renditions([ahead, close, behind])]
    assert titles.count("One variant lags its peers at the live edge") == 1
