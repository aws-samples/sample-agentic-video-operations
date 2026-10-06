"""Every fixture scenario replays through the full pipeline to its expected finding."""

import pytest

from hls_doctor.workflows.build_probe_context import build_probe_context
from hls_doctor.workflows.inspect_stream import inspect_stream

VOD_ENTRY = "https://demo.example/vod/master.m3u8"
LIVE_ENTRY = "https://demo.example/live/master.m3u8"
LLHLS_ENTRY = "https://demo.example/llhls/master.m3u8"

# scenario -> (entry url, watch seconds, expected status, expected finding title)
EXPECTATIONS = {
    "hls_clean_vod": (VOD_ENTRY, 0, "healthy", None),
    "hls_clean_live": (LIVE_ENTRY, 10, "healthy", None),
    "hls_missing_variant": (VOD_ENTRY, 0, "degraded", "Unreachable media playlist"),
    "hls_wrong_version": (
        VOD_ENTRY, 0, "degraded", "Declared HLS version below the features in use",
    ),
    "hls_targetduration_exceeded": (
        VOD_ENTRY, 0, "degraded", "Segment duration exceeds EXT-X-TARGETDURATION",
    ),
    "hls_broken_map": (VOD_ENTRY, 0, "degraded", "Unreachable init section"),
    "hls_expired_key": (VOD_ENTRY, 0, "degraded", "Unreachable key"),
    "hls_subtitle_playlist_404": (VOD_ENTRY, 0, "degraded", "Unreachable media playlist"),
    "hls_pts_regression": (
        VOD_ENTRY, 0, "degraded", "Video timestamps go backwards inside a segment",
    ),
    "hls_segment_race": (
        LIVE_ENTRY, 10, "degraded", "Segments are advertised before they are available",
    ),
    "hls_frozen_playlist": (LIVE_ENTRY, 10, "degraded", "Frozen live playlist"),
    "hls_stale_cdn_manifest": (
        LIVE_ENTRY, 10, "degraded", "Stale live playlist served from cache",
    ),
    "hls_signaled_gap": (LIVE_ENTRY, 0, "healthy", None),
    "hls_audio_drift": (LIVE_ENTRY, 0, "at-risk", "Audio rendition drifts from video"),
    "hls_missing_discontinuity": (
        LIVE_ENTRY, 0, "degraded", "Codec change without a signaled discontinuity",
    ),
    "hls_cueout_without_cuein": (
        LIVE_ENTRY, 0, "at-risk", "Ad break opened without a matching CUE-IN",
    ),
    "hls_scte35_duration_mismatch": (
        LIVE_ENTRY, 0, "at-risk", "Ad break duration disagrees with its SCTE-35 payload",
    ),
    "hls_interstitial_asset_404": (
        LIVE_ENTRY, 0, "degraded", "Interstitial asset list is unreachable",
    ),
    "hls_interstitial_bad_asset": (
        LIVE_ENTRY, 0, "degraded", "Interstitial asset uses an incompatible video codec",
    ),
    "hls_interstitial_rendition_mismatch": (
        LIVE_ENTRY, 0, "degraded", "Date-range events are missing from a rendition",
    ),
    "hls_variant_lag": (LIVE_ENTRY, 0, "at-risk", "One variant lags its peers at the live edge"),
    "hls_clean_llhls": (LLHLS_ENTRY, 0, "healthy", None),
    "hls_llhls_blocking_reload": (
        LLHLS_ENTRY, 0, "degraded", "Blocking playlist reload returns a stale generation",
    ),
    "hls_stale_rendition_report": (LLHLS_ENTRY, 0, "at-risk", "Stale rendition report"),
    "hls_preload_hint_404": (LLHLS_ENTRY, 0, "at-risk", "PRELOAD-HINT never resolves"),
    "hls_steering_pathway_failure": (
        VOD_ENTRY, 0, "degraded", "Steering pathway 'B' is failing while A serves",
    ),
}  # fmt: skip


@pytest.mark.parametrize(("scenario", "expectation"), EXPECTATIONS.items())
def test_scenario_produces_the_expected_diagnosis(scenario, expectation, demo_settings):
    entry, watch_seconds, status, expected_title = expectation
    report = inspect_stream(
        entry,
        build_probe_context(demo_settings(scenario)),
        watch_seconds=watch_seconds or None,
    )

    assert report.summary.status == status
    titles = [finding.title for finding in report.findings]
    if expected_title is None:
        assert report.summary.errors == 0 and report.summary.fatal == 0
    else:
        assert expected_title in titles


def test_clean_vod_inventory_and_features(demo_settings):
    report = inspect_stream(VOD_ENTRY, build_probe_context(demo_settings("hls_clean_vod")))
    assert report.summary.presentation_type == "vod"
    assert len(report.presentation.variants) == 4
    assert len(report.presentation.renditions) == 2
    assert "alternate-audio" in report.summary.features
    assert "encryption" in report.summary.features


def test_findings_reference_recorded_evidence(demo_settings):
    report = inspect_stream(VOD_ENTRY, build_probe_context(demo_settings("hls_broken_map")))
    [finding] = [f for f in report.findings if f.title == "Unreachable init section"]
    [observation] = finding.observations
    assert observation.evidence_id is not None
    exchange = report.evidence.exchanges[observation.evidence_id]
    assert exchange.status == 404 and "init.mp4" in exchange.requested_url


def test_the_race_finding_carries_the_evidence_timeline(demo_settings):
    report = inspect_stream(
        LIVE_ENTRY,
        build_probe_context(demo_settings("hls_segment_race")),
        watch_seconds=10,
    )
    [race] = [
        finding for finding in report.findings
        if finding.title == "Segments are advertised before they are available"
    ]  # fmt: skip
    assert race.confidence.value == "high"  # reproduced on two renditions
    assert len(race.affected_resources) == 2
    statements = [observation.statement for observation in race.observations]
    assert any("404" in statement for statement in statements)
    assert any("200" in statement for statement in statements)


def test_the_signaled_gap_is_reported_as_info_not_error(demo_settings):
    report = inspect_stream(LIVE_ENTRY, build_probe_context(demo_settings("hls_signaled_gap")))
    [gap] = [
        finding for finding in report.findings
        if finding.title == "Unavailable segment is correctly signaled with EXT-X-GAP"
    ]  # fmt: skip
    assert gap.severity.value == "INFO"
    assert report.summary.errors == 0
