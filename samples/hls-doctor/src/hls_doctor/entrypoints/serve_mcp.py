"""Register the HLS Doctor inspection tools as read-only MCP tools over stdio."""

from fastmcp import FastMCP

from hls_doctor.entrypoints.report_tool_failure import report_tool_failure
from hls_doctor.settings.runtime_settings import (
    HlsDoctorSettings,
    load_hls_doctor_settings,
)
from hls_doctor.tool_surface.create_analysis_tools import create_analysis_tools
from hls_doctor.tool_surface.create_inspection_tools import create_inspection_tools
from hls_doctor.tool_surface.create_probe_tools import create_probe_tools

READ_ONLY = {"readOnlyHint": True}


def build_hls_doctor_server(settings: HlsDoctorSettings | None = None) -> FastMCP:
    """Every tool is read-only; there are no write tools in this sample."""
    runtime = settings or load_hls_doctor_settings()
    server = FastMCP(
        "HLS Doctor",
        instructions=(
            "HLS stream diagnostics. Start with inspect_stream for a full report;"
            " use the narrower tools to follow a specific lead."
        ),
    )
    for tool in [
        *create_inspection_tools(runtime),
        *create_probe_tools(runtime),
        *create_analysis_tools(runtime),
    ]:
        server.tool(report_tool_failure(tool), annotations=READ_ONLY)
    return server


def main() -> None:
    build_hls_doctor_server().run(show_banner=False)


if __name__ == "__main__":
    main()
