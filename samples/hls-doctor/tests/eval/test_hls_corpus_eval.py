"""Scored acceptance evaluation over the whole fixture corpus (run with `just eval`).

Stricter than the scenario tests: each case pins its expected findings AND the
set of ERROR/FATAL titles that may appear at all, so a new false positive on
any corpus case fails the evaluation. Results are written to .cache/.
"""

import json
from pathlib import Path

import pytest

from hls_doctor.workflows.build_probe_context import build_probe_context
from hls_doctor.workflows.inspect_stream import inspect_stream

pytestmark = pytest.mark.eval

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
RESULTS_PATH = REPOSITORY_ROOT / ".cache" / "hls-eval-results.json"

VOD = "https://demo.example/vod/master.m3u8"
LIVE = "https://demo.example/live/master.m3u8"
LLHLS = "https://demo.example/llhls/master.m3u8"

# scenario: (entry, watch_seconds, must_have titles, allowed ERROR/FATAL titles)
CASES: dict[str, tuple[str, float, list[str], list[str]]] = {
    "hls_clean_vod": (VOD, 0, [], []),
    "hls_clean_live": (LIVE, 10, [], []),
    "hls_clean_llhls": (LLHLS, 0, [], []),
    "hls_missing_variant": (
        VOD,
        0,
        ["Unreachable media playlist"],
        ["Unreachable media playlist"],
    ),
    "hls_wrong_version": (
        VOD,
        0,
        ["Declared HLS version below the features in use"],
        ["Declared HLS version below the features in use"],
    ),
    "hls_targetduration_exceeded": (
        VOD,
        0,
        ["Segment duration exceeds EXT-X-TARGETDURATION"],
        ["Segment duration exceeds EXT-X-TARGETDURATION"],
    ),
    "hls_broken_map": (VOD, 0, ["Unreachable init section"], ["Unreachable init section"]),
    "hls_expired_key": (VOD, 0, ["Unreachable key"], ["Unreachable key"]),
    "hls_subtitle_playlist_404": (
        VOD,
        0,
        ["Unreachable media playlist"],
        ["Unreachable media playlist"],
    ),
    "hls_pts_regression": (
        VOD,
        0,
        ["Video timestamps go backwards inside a segment"],
        ["Video timestamps go backwards inside a segment"],
    ),
    "hls_segment_race": (
        LIVE,
        10,
        ["Segments are advertised before they are available"],
        ["Segments are advertised before they are available"],
    ),
    "hls_frozen_playlist": (LIVE, 10, ["Frozen live playlist"], ["Frozen live playlist"]),
    "hls_stale_cdn_manifest": (
        LIVE,
        10,
        ["Stale live playlist served from cache"],
        ["Stale live playlist served from cache", "Frozen live playlist"],
    ),
    "hls_signaled_gap": (
        LIVE,
        0,
        ["Unavailable segment is correctly signaled with EXT-X-GAP"],
        [],
    ),
    "hls_audio_drift": (LIVE, 0, ["Audio rendition drifts from video"], []),
    "hls_missing_discontinuity": (
        LIVE,
        0,
        ["Codec change without a signaled discontinuity"],
        ["Codec change without a signaled discontinuity"],
    ),
    "hls_cueout_without_cuein": (
        LIVE,
        0,
        ["Ad break opened without a matching CUE-IN"],
        [],
    ),
    "hls_scte35_duration_mismatch": (
        LIVE,
        0,
        ["Ad break duration disagrees with its SCTE-35 payload"],
        [],
    ),
    "hls_interstitial_asset_404": (
        LIVE,
        0,
        ["Interstitial asset list is unreachable"],
        ["Interstitial asset list is unreachable"],
    ),
    "hls_interstitial_bad_asset": (
        LIVE,
        0,
        ["Interstitial asset uses an incompatible video codec"],
        ["Interstitial asset uses an incompatible video codec"],
    ),
    "hls_interstitial_rendition_mismatch": (
        LIVE,
        0,
        ["Date-range events are missing from a rendition"],
        ["Date-range events are missing from a rendition"],
    ),
    "hls_variant_lag": (LIVE, 0, ["One variant lags its peers at the live edge"], []),
    "hls_llhls_blocking_reload": (
        LLHLS,
        0,
        ["Blocking playlist reload returns a stale generation"],
        ["Blocking playlist reload returns a stale generation"],
    ),
    "hls_stale_rendition_report": (LLHLS, 0, ["Stale rendition report"], []),
    "hls_preload_hint_404": (LLHLS, 0, ["PRELOAD-HINT never resolves"], []),
    "hls_steering_pathway_failure": (
        VOD,
        0,
        ["Steering pathway 'B' is failing while A serves"],
        ["Unreachable media playlist"],
    ),
}


@pytest.mark.parametrize(("scenario", "case"), CASES.items())
def test_corpus_case_scores_exactly(scenario, case, demo_settings):
    entry, watch_seconds, must_have, allowed_severe = case
    report = inspect_stream(
        entry,
        build_probe_context(demo_settings(scenario)),
        watch_seconds=watch_seconds or None,
    )
    titles = [finding.title for finding in report.findings]
    severe = [
        finding.title for finding in report.findings if finding.severity.value in ("ERROR", "FATAL")
    ]
    missing = [title for title in must_have if title not in titles]
    unexpected = [title for title in severe if title not in allowed_severe]
    record_result(scenario, missing, unexpected)
    assert not missing, f"missing expected findings: {missing}"
    assert not unexpected, f"unexpected severe findings: {unexpected}"


def record_result(scenario: str, missing: list[str], unexpected: list[str]) -> None:
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = json.loads(RESULTS_PATH.read_text()) if RESULTS_PATH.is_file() else {}
    existing[scenario] = {"missing": missing, "unexpected_severe": unexpected}
    RESULTS_PATH.write_text(json.dumps(existing, indent=1, sort_keys=True) + "\n")
