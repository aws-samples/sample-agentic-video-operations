"""Deep-probe tools: live watch, media probe and the Apple validator crosscheck."""

from pydantic import BaseModel, Field

from hls_doctor.adapters.applevalidator.validator_report import ValidatorReport
from hls_doctor.adapters.ffprobe.probe_report import SegmentProbe
from hls_doctor.adapters.http.classify_http_error import require_usable_entry_url
from hls_doctor.domain.correlate.finding_model import Finding
from hls_doctor.settings.runtime_settings import HlsDoctorSettings
from hls_doctor.tool_surface.create_inspection_tools import resolve_default_url
from hls_doctor.workflows.build_probe_context import build_probe_context
from hls_doctor.workflows.watch_stream import watch_stream
from media_ops_contracts.domain_pack import ReadTool
from media_ops_contracts.tool_failure import FailureKind, ToolFailure


class WatchSummary(BaseModel):
    entry_url: str
    watched_playlists: list[str] = Field(default_factory=list)
    reloads_per_playlist: dict[str, int] = Field(default_factory=dict)
    findings: list[Finding] = Field(default_factory=list)


def create_probe_tools(settings: HlsDoctorSettings) -> list[ReadTool]:
    """Each tool builds a fresh probe context, so DEMO replay applies per call."""

    def watch_playlist(url: str = "", duration_seconds: float = 0) -> WatchSummary:
        """Reload the live playlists over a bounded window and report live defects.

        Duration is clamped to HLS_MAX_WATCH_SECONDS; 0 means the default window.
        In demo mode an empty url defaults to the scenario's entry manifest.
        """
        context = build_probe_context(settings)
        report = watch_stream(
            resolve_default_url(url, settings),
            context,
            duration_seconds=duration_seconds or None,
        )
        return WatchSummary(
            entry_url=report.entry_url,
            watched_playlists=report.watched_playlists,
            reloads_per_playlist=report.reloads_per_playlist,
            findings=report.findings,
        )

    def probe_segment(url: str) -> SegmentProbe:
        """Probe one segment or init section with ffprobe: streams, format, timestamps."""
        require_usable_entry_url(url)
        probe = build_probe_context(settings).media_probe()
        if probe is None:
            raise ToolFailure(
                FailureKind.INVALID_REQUEST,
                "Media probing is unavailable: ffprobe is not installed, or this demo"
                " scenario records no media output.",
                "Install FFmpeg, or pick a scenario with recorded ffprobe output.",
            )
        return probe(url, with_packets=True)

    def run_apple_validator(url: str = "") -> ValidatorReport:
        """Run Apple's mediastreamvalidator as an independent conformance crosscheck."""
        context = build_probe_context(settings)
        if context.validator is None:
            raise ToolFailure(
                FailureKind.INVALID_REQUEST,
                "No validator is available in this mode.",
                "Install Apple's HLS Tools (macOS) to run the crosscheck.",
            )
        return context.validator(resolve_default_url(url, settings))

    return [watch_playlist, probe_segment, run_apple_validator]
