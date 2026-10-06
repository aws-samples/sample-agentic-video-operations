"""Every fixture scenario replays through the full pipeline to its expected finding."""

import pytest

from hls_doctor.workflows.build_probe_context import build_probe_context
from hls_doctor.workflows.inspect_stream import inspect_stream

ENTRY = "https://demo.example/vod/master.m3u8"

EXPECTATIONS = {
    "hls_clean_vod": ("healthy", None),
    "hls_missing_variant": ("degraded", "Unreachable media playlist"),
    "hls_wrong_version": ("degraded", "Declared HLS version below the features in use"),
    "hls_targetduration_exceeded": (
        "degraded",
        "Segment duration exceeds EXT-X-TARGETDURATION",
    ),
    "hls_broken_map": ("degraded", "Unreachable init section"),
    "hls_expired_key": ("degraded", "Unreachable key"),
    "hls_subtitle_playlist_404": ("degraded", "Unreachable media playlist"),
}


@pytest.mark.parametrize(("scenario", "expectation"), EXPECTATIONS.items())
def test_scenario_produces_the_expected_diagnosis(scenario, expectation, demo_settings):
    status, expected_title = expectation
    report = inspect_stream(ENTRY, build_probe_context(demo_settings(scenario)))

    assert report.summary.status == status
    titles = [finding.title for finding in report.findings]
    if expected_title is None:
        assert report.summary.errors == 0 and report.summary.fatal == 0
    else:
        assert expected_title in titles


def test_clean_vod_inventory_and_features(demo_settings):
    report = inspect_stream(ENTRY, build_probe_context(demo_settings("hls_clean_vod")))
    assert report.summary.presentation_type == "vod"
    assert len(report.presentation.variants) == 4
    assert len(report.presentation.renditions) == 2
    assert "alternate-audio" in report.summary.features
    assert "encryption" in report.summary.features


def test_findings_reference_recorded_evidence(demo_settings):
    report = inspect_stream(ENTRY, build_probe_context(demo_settings("hls_broken_map")))
    [finding] = [f for f in report.findings if f.title == "Unreachable init section"]
    [observation] = finding.observations
    assert observation.evidence_id is not None
    exchange = report.evidence.exchanges[observation.evidence_id]
    assert exchange.status == 404 and "init.mp4" in exchange.requested_url
