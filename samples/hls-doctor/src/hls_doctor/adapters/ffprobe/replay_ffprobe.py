"""Fixture-backed media probe, keyed by URL. Fails closed like the HTTP replay."""

from pathlib import Path

from hls_doctor.adapters.ffprobe.probe_report import (
    ProbeSegment,
    SegmentProbe,
    parse_ffprobe_output,
)
from media_ops_contracts.load_fixture import load_fixture
from media_ops_contracts.tool_failure import FailureKind, ToolFailure


def create_replay_probe(fixtures_dir: Path, scenario: str) -> ProbeSegment:
    """Answers from fixtures/<scenario>/ffprobe.probe_segment.json."""
    recorded = load_fixture(fixtures_dir, scenario, "ffprobe.probe_segment")

    def probe(url: str, *, with_packets: bool = False) -> SegmentProbe:
        payload = recorded.get(url)
        if payload is None:
            raise ToolFailure(
                FailureKind.INVALID_REQUEST,
                f"No recorded ffprobe output for {url} in scenario {scenario}.",
                "Record it with scripts/record_hls_fixtures.py or skip media probing.",
            )
        return parse_ffprobe_output(url, payload)

    return probe
