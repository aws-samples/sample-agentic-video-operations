from pathlib import Path

import pytest

from cmcd_mcp.adapters.influxdb.analyze_buffer_events import analyze_buffer_events
from cmcd_mcp.adapters.influxdb.execute_flux_query import execute_flux_query
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


def test_get_session_details_groups_points_by_metric():
    query = replay_influxdb_query(
        FIXTURES_DIR,
        "cmcd_rebuffering",
        "influxdb.query_session_details",
    )
    result = get_session_details("demo-session-west", query_influxdb=query)
    assert set(result.metrics) == {"cmcd_br", "cmcd_bl"}
    assert result.metrics["cmcd_bl"][0].value == 80


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


def test_identify_playback_errors_reports_buffer_and_startup_issues():
    query = replay_influxdb_query(
        FIXTURES_DIR,
        "cmcd_rebuffering",
        "influxdb.query_playback_errors",
    )
    result = identify_playback_errors(query_influxdb=query)
    kinds = {issue.kind for issue in result.issues}
    assert PlaybackIssueKind.BUFFER_UNDERRUN in kinds
    assert PlaybackIssueKind.SUDDEN_BUFFER_DROP in kinds
    assert PlaybackIssueKind.EXCESSIVE_STARTUP_DELAY in kinds


def test_list_session_and_content_ids_deduplicates_values():
    query = replay_influxdb_query(
        FIXTURES_DIR,
        "cmcd_rebuffering",
        "influxdb.query_session_and_content_ids",
    )
    result = list_session_and_content_ids(query_influxdb=query)
    assert result.session_ids == ["demo-session-west", "demo-session-east"]
    assert result.content_ids == ["demo-content", "demo-live-event"]


def test_execute_flux_query_wraps_raw_records_in_a_typed_result():
    query = replay_influxdb_query(
        FIXTURES_DIR,
        "cmcd_rebuffering",
        "influxdb.execute_flux_query",
    )
    result = execute_flux_query(
        'from(bucket: "cmcd-metrics")',
        query_influxdb=query,
    )
    assert result.record_count == 1
    assert result.records[0]["cmcd_sid"] == "demo-session-west"


@pytest.mark.parametrize(
    "flux",
    [
        'from(bucket: "cmcd-metrics") |> filter(fn: (r) => r.host =~ /edge.*/)',
        'from(bucket: "cmcd-metrics") |> filter(fn: (r) => r.host !~ /test.*/)',
    ],
)
def test_execute_flux_query_allows_regex_comparisons(flux):
    queried = False

    def query_influxdb(_):
        nonlocal queried
        queried = True
        return []

    execute_flux_query(flux, query_influxdb=query_influxdb)

    assert queried is True


@pytest.mark.parametrize(
    "flux",
    [
        'from(bucket: "source") |> to(bucket: "destination")',
        'import "http"\nhttp.post(url: "https://example.com")',
        "writer = to\nwriter()",
    ],
)
def test_execute_flux_query_rejects_queries_that_can_have_side_effects(flux):
    queried = False

    def query_influxdb(_):
        nonlocal queried
        queried = True
        return []

    with pytest.raises(ToolFailure) as failure:
        execute_flux_query(flux, query_influxdb=query_influxdb)

    assert failure.value.kind is FailureKind.INVALID_REQUEST
    assert queried is False
