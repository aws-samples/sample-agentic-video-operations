"""Register the CMCD adapters as read-only MCP tools and serve stdio."""

from collections.abc import Callable
from functools import partial
from typing import Any, cast

from fastmcp import FastMCP

from cmcd_mcp.adapters.influxdb.analyze_buffer_events import (
    BufferAnalysis,
)
from cmcd_mcp.adapters.influxdb.analyze_buffer_events import (
    analyze_buffer_events as read_buffer_events,
)
from cmcd_mcp.adapters.influxdb.get_average_bitrate import (
    AverageBitrate,
)
from cmcd_mcp.adapters.influxdb.get_average_bitrate import (
    get_average_bitrate as read_average_bitrate,
)
from cmcd_mcp.adapters.influxdb.get_session_details import (
    SessionDetails,
)
from cmcd_mcp.adapters.influxdb.get_session_details import (
    get_session_details as read_session_details,
)
from cmcd_mcp.adapters.influxdb.identify_playback_errors import (
    PlaybackErrorAnalysis,
)
from cmcd_mcp.adapters.influxdb.identify_playback_errors import (
    identify_playback_errors as read_playback_errors,
)
from cmcd_mcp.adapters.influxdb.list_session_and_content_ids import (
    SessionAndContentIds,
)
from cmcd_mcp.adapters.influxdb.list_session_and_content_ids import (
    list_session_and_content_ids as read_session_and_content_ids,
)
from cmcd_mcp.adapters.influxdb.query_influxdb import query_influxdb
from cmcd_mcp.adapters.influxdb.replay_influxdb_query import replay_influxdb_query
from cmcd_mcp.entrypoints.report_tool_failure import report_tool_failure
from cmcd_mcp.settings.runtime_settings import RuntimeSettings

QueryInfluxDb = Callable[[str], list[dict[str, Any]]]
READ_ONLY = {"readOnlyHint": True}


def build_cmcd_server(settings: RuntimeSettings | None = None) -> FastMCP:
    """Build a server whose tools share settings but not policy or credentials."""
    runtime = settings or RuntimeSettings()
    server = FastMCP(
        "CMCD MCP Server",
        instructions="Read-only analysis of CMCD viewer telemetry stored in InfluxDB.",
    )

    average_query = _select_query(runtime, "influxdb.query_average_bitrate")
    session_query = _select_query(runtime, "influxdb.query_session_details")
    buffer_query = _select_query(runtime, "influxdb.query_buffer_events")
    playback_query = _select_query(runtime, "influxdb.query_playback_errors")
    ids_query = _select_query(runtime, "influxdb.query_session_and_content_ids")

    @server.tool(annotations=READ_ONLY)
    @report_tool_failure
    def get_average_bitrate(
        time_range: str = "-24h",
        cmcd_sid: str | None = None,
        cmcd_cid: str | None = None,
    ) -> AverageBitrate:
        """Get mean requested bitrate, optionally filtered by session or content."""
        return read_average_bitrate(
            time_range,
            cmcd_sid,
            cmcd_cid,
            query_influxdb=average_query,
        )

    @server.tool(annotations=READ_ONLY)
    @report_tool_failure
    def get_session_details(cmcd_sid: str, time_range: str = "-24h") -> SessionDetails:
        """Get chronological CMCD metrics for one playback session."""
        return read_session_details(cmcd_sid, time_range, query_influxdb=session_query)

    @server.tool(annotations=READ_ONLY)
    @report_tool_failure
    def analyze_buffer_events(
        time_range: str = "-24h",
        cmcd_sid: str | None = None,
        threshold_ms: int = 500,
    ) -> BufferAnalysis:
        """Find buffer events below a threshold."""
        return read_buffer_events(
            time_range,
            cmcd_sid,
            threshold_ms,
            query_influxdb=buffer_query,
        )

    @server.tool(annotations=READ_ONLY)
    @report_tool_failure
    def identify_playback_errors(
        time_range: str = "-24h",
        cmcd_sid: str | None = None,
    ) -> PlaybackErrorAnalysis:
        """Detect starvation signals and sudden buffer drops with startup context."""
        return read_playback_errors(time_range, cmcd_sid, query_influxdb=playback_query)

    @server.tool(annotations=READ_ONLY)
    @report_tool_failure
    def list_session_and_content_ids(
        time_range: str = "-24h",
        limit: int = 100,
    ) -> SessionAndContentIds:
        """List distinct CMCD session and content ids."""
        return read_session_and_content_ids(time_range, limit, query_influxdb=ids_query)

    return server


def _select_query(settings: RuntimeSettings, fixture_name: str) -> QueryInfluxDb:
    if settings.demo:
        return replay_influxdb_query(
            settings.fixtures_dir,
            settings.demo_scenario,
            fixture_name,
        )
    return partial(
        query_influxdb,
        url=cast(str, settings.influxdb_url),
        token=cast(str, settings.influxdb_token),
        org=cast(str, settings.influxdb_org),
        verify_ssl=settings.verify_ssl,
    )


def main() -> None:
    build_cmcd_server().run()


if __name__ == "__main__":
    main()
