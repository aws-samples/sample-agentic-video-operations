from datetime import UTC, datetime
from pathlib import Path

import pytest

from cmcd_mcp.adapters.influxdb.analyze_buffer_events import analyze_buffer_events
from cmcd_mcp.adapters.influxdb.get_average_bitrate import get_average_bitrate
from cmcd_mcp.adapters.influxdb.get_session_details import get_session_details
from cmcd_mcp.adapters.influxdb.identify_playback_errors import (
    PlaybackIssueKind,
    identify_playback_errors,
)
from cmcd_mcp.adapters.influxdb.list_session_and_content_ids import (
    list_session_and_content_ids,
)
from cmcd_mcp.adapters.influxdb.replay_influxdb_query import replay_influxdb_query
from media_ops_contracts.tool_failure import FailureKind, ToolFailure

FIXTURES_DIR = Path(__file__).parents[4] / "fixtures"


def test_get_average_bitrate_returns_a_typed_mean():
    query = replay_influxdb_query(
        FIXTURES_DIR,
        "cmcd_rebuffering",
        "influxdb.query_average_bitrate",
    )
    result = get_average_bitrate(
        "-1h",
        "demo-session-west",
        query_influxdb=query,
    )
    assert result.average_bitrate_kbps == 4200
    assert result.session_id == "demo-session-west"


def test_query_filters_disable_flux_interpolation_for_untrusted_ids():
    captured_flux = ""

    def query_influxdb(flux):
        nonlocal captured_flux
        captured_flux = flux
        return [{"_value": 4200}]

    get_average_bitrate(
        cmcd_sid="${dangerous.session}",
        cmcd_cid="${dangerous.content}",
        query_influxdb=query_influxdb,
    )

    assert r'"\${dangerous.session}"' in captured_flux
    assert r'"\${dangerous.content}"' in captured_flux


def test_get_average_bitrate_filters_non_positive_values_and_keeps_optional_ids():
    captured_flux = ""

    def query_influxdb(flux):
        nonlocal captured_flux
        captured_flux = flux
        return [{"_value": 3200}]

    result = get_average_bitrate(
        cmcd_sid="session-1",
        cmcd_cid="content-1",
        query_influxdb=query_influxdb,
    )

    assert 'r["_value"] > 0' in captured_flux
    assert 'r["cmcd_sid"] == "session-1"' in captured_flux
    assert 'r["cmcd_cid"] == "content-1"' in captured_flux
    assert result.session_id == "session-1"
    assert result.content_id == "content-1"


@pytest.mark.parametrize("placeholder", [0, -1, 0.0])
def test_get_average_bitrate_reports_non_positive_results_as_missing(placeholder):
    with pytest.raises(ToolFailure) as failure:
        get_average_bitrate(query_influxdb=lambda _: [{"_value": placeholder}])

    assert failure.value.kind is FailureKind.RESOURCE_NOT_FOUND
    assert failure.value.message == "No bitrate data matched the requested criteria."


def test_get_session_details_sorts_interleaved_flux_tables():
    query = replay_influxdb_query(
        FIXTURES_DIR,
        "cmcd_rebuffering",
        "influxdb.query_session_details",
    )
    result = get_session_details("demo-session-west", query_influxdb=query)

    assert set(result.metrics) == {"cmcd_br", "cmcd_bl"}
    assert result.start_time == datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)
    assert result.end_time == datetime(2026, 10, 5, 12, 0, 5, tzinfo=UTC)
    assert [point.value for point in result.metrics["cmcd_br"]] == [4100, 4200, 4300]
    assert [point.value for point in result.metrics["cmcd_bl"]] == [120, 80, 0]
    for points in result.metrics.values():
        assert [point.at for point in points] == sorted(point.at for point in points)


def test_get_session_details_omits_missing_and_non_positive_placeholders():
    def query(_):
        return [
            {"_time": "2026-10-05T12:00:00Z", "_field": "cmcd_br", "_value": 0},
            {"_time": "2026-10-05T12:00:01Z", "_field": "cmcd_tb", "_value": -1},
            {"_time": "2026-10-05T12:00:02Z", "_field": "cmcd_mtp", "_value": None},
            {"_time": "2026-10-05T12:00:02Z", "_field": "cmcd_bl", "_value": 0},
            {"_time": "2026-10-05T12:00:03Z", "_field": "cmcd_br", "_value": 2500},
        ]

    result = get_session_details("session-1", query_influxdb=query)

    assert "cmcd_tb" not in result.metrics
    assert "cmcd_mtp" not in result.metrics
    assert [point.value for point in result.metrics["cmcd_br"]] == [2500]
    assert [point.value for point in result.metrics["cmcd_bl"]] == [0]


def test_get_session_details_reports_placeholder_only_session_as_missing():
    def query(_):
        return [
            {"_time": "2026-10-05T12:00:00Z", "_field": "cmcd_br", "_value": 0},
            {"_time": "2026-10-05T12:00:01Z", "_field": "cmcd_tb", "_value": -1},
            {"_time": "2026-10-05T12:00:02Z", "_field": "cmcd_mtp", "_value": None},
        ]

    with pytest.raises(ToolFailure) as failure:
        get_session_details("session-1", query_influxdb=query)

    assert failure.value.kind is FailureKind.RESOURCE_NOT_FOUND
    assert failure.value.message == "No usable CMCD metrics were found for session session-1."


def test_analyze_buffer_events_replays_the_regional_incident_fixture():
    query = replay_influxdb_query(
        FIXTURES_DIR,
        "cmcd_rebuffering",
        "influxdb.query_buffer_events",
    )
    result = analyze_buffer_events(query_influxdb=query)
    assert result.total_events == 5
    assert result.low_buffer_count == 3
    assert {event.edge_location for event in result.low_buffer_events} == {"demo-edge-west"}
    assert {event.cdn for event in result.low_buffer_events} == {"demo-cdn"}


def test_identify_playback_errors_uses_starvation_and_boolean_startup_signals():
    query = replay_influxdb_query(
        FIXTURES_DIR,
        "cmcd_rebuffering",
        "influxdb.query_playback_errors",
    )
    result = identify_playback_errors(query_influxdb=query)
    kinds = {issue.kind for issue in result.issues}
    assert PlaybackIssueKind.BUFFER_STARVATION in kinds
    assert PlaybackIssueKind.SUDDEN_BUFFER_DROP in kinds
    assert result.startup_observed is True
    starvation = next(
        issue for issue in result.issues if issue.kind is PlaybackIssueKind.BUFFER_STARVATION
    )
    assert starvation.observed_flag is True
    assert starvation.observed_ms is None


def test_list_session_and_content_ids_deduplicates_values():
    query = replay_influxdb_query(
        FIXTURES_DIR,
        "cmcd_rebuffering",
        "influxdb.query_session_and_content_ids",
    )
    result = list_session_and_content_ids(query_influxdb=query)
    assert result.session_ids == ["demo-session-west", "demo-session-east"]
    assert result.content_ids == ["demo-content", "demo-live-event"]
