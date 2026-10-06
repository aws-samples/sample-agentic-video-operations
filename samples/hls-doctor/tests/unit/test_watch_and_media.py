from hls_doctor.adapters.ffprobe.probe_report import parse_ffprobe_output
from hls_doctor.domain.correlate.correlation_rules import classify_race
from hls_doctor.domain.media.analyze_timestamps import analyze_timestamps
from hls_doctor.domain.media.detect_media_defects import detect_media_defects
from hls_doctor.domain.playlist.parse_media_playlist import parse_media_playlist
from hls_doctor.domain.playlist.tokenize_playlist import tokenize_playlist
from hls_doctor.domain.watch.detect_live_defects import detect_live_defects
from hls_doctor.domain.watch.playlist_snapshot import build_snapshot

URL = "https://demo.example/live/v1080/prog.m3u8"


def snapshot(at_ms: int, first_msn: int, *, age: str | None = None, etag: str | None = None):
    body = f"#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXT-X-MEDIA-SEQUENCE:{first_msn}\n" + "".join(
        f"#EXTINF:4.0,\nseg{first_msn + i}.m4s\n" for i in range(3)
    )
    media = parse_media_playlist(tokenize_playlist(body))
    return build_snapshot(URL, at_ms, f"e{at_ms}", media, etag, age)


def test_an_advancing_playlist_raises_no_live_defects() -> None:
    snapshots = [snapshot(0, 100), snapshot(4000, 101), snapshot(8000, 102)]
    assert detect_live_defects(URL, snapshots, 4) == []


def test_a_frozen_playlist_is_detected_after_two_target_durations() -> None:
    snapshots = [snapshot(0, 100), snapshot(4000, 100), snapshot(9000, 100)]
    [finding] = detect_live_defects(URL, snapshots, 4)
    assert finding.title == "Frozen live playlist"


def test_sequence_regression_is_detected() -> None:
    snapshots = [snapshot(0, 100), snapshot(4000, 90)]
    titles = [finding.title for finding in detect_live_defects(URL, snapshots, 4)]
    assert "MEDIA-SEQUENCE went backwards" in titles


def test_growing_age_with_constant_etag_is_a_stale_cache() -> None:
    snapshots = [
        snapshot(0, 100, age="30", etag='"g1"'),
        snapshot(4000, 100, age="36", etag='"g1"'),
        snapshot(9000, 100, age="42", etag='"g1"'),
    ]
    titles = [finding.title for finding in detect_live_defects(URL, snapshots, 4)]
    assert "Stale live playlist served from cache" in titles


def probe(url: str, pts: list[float]):
    payload = {
        "streams": [{"index": 0, "codec_type": "video", "codec_name": "h264"}],
        "packets": [{"codec_type": "video", "pts_time": str(value)} for value in pts],
        "format": {"format_name": "mov,mp4,m4a", "duration": "6.0"},
    }
    return parse_ffprobe_output(url, payload)


def test_monotonic_timestamps_are_clean() -> None:
    analysis = analyze_timestamps(probe("u", [0.0, 0.033, 0.066]))
    assert analysis.regressions == [] and analysis.packet_count == 3


def test_without_dts_a_pts_regression_becomes_an_error_finding() -> None:
    findings = detect_media_defects([probe("u", [0.0, 0.1, 0.05])])
    assert findings[0].title == "Video timestamps go backwards inside a segment"
    assert findings[0].severity.value == "ERROR"
    assert findings[0].confidence.value == "high"


def bframe_probe(url: str):
    payload = {
        "streams": [{"index": 0, "codec_type": "video", "codec_name": "h264"}],
        "packets": [
            {"codec_type": "video", "dts_time": "0.000", "pts_time": "0.000"},
            {"codec_type": "video", "dts_time": "0.033", "pts_time": "0.100"},
            {"codec_type": "video", "dts_time": "0.066", "pts_time": "0.033"},
            {"codec_type": "video", "dts_time": "0.099", "pts_time": "0.066"},
        ],
        "format": {"format_name": "mov,mp4,m4a"},
    }
    return parse_ffprobe_output(url, payload)


def test_bframe_reordering_is_not_a_regression() -> None:
    analysis = analyze_timestamps(bframe_probe("u"))
    assert analysis.clock == "dts" and analysis.regressions == []
    assert detect_media_defects([bframe_probe("u")]) == []


def test_a_dts_regression_is_an_error_even_with_bframes() -> None:
    broken = bframe_probe("u")
    broken.packets[3].dts_time = 0.01
    findings = detect_media_defects([broken])
    assert findings[0].title == "Video timestamps go backwards inside a segment"


class FakeExchange:
    def __init__(self, at_ms: int, status: int) -> None:
        self.at_ms = at_ms
        self.status = status
        self.transport_error = None

    @property
    def ok(self) -> bool:
        return self.status < 400


def test_classify_race_requires_failure_then_success() -> None:
    race = classify_race(
        [("e1", FakeExchange(100, 404)), ("e2", FakeExchange(500, 404)),
         ("e3", FakeExchange(1400, 200))]
    )  # fmt: skip
    assert race is not None
    observations, delay = race
    assert delay == 1300 and len(observations) == 3
    assert classify_race([("e1", FakeExchange(100, 200))]) is None
    assert classify_race([("e1", FakeExchange(100, 404))]) is None
