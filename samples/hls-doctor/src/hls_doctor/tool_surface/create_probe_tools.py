"""Deep-probe tools: live watch, media probe and the Apple validator crosscheck."""

from pydantic import BaseModel, Field

from hls_doctor.adapters.applevalidator.validator_report import ValidatorReport
from hls_doctor.adapters.ffprobe.probe_report import SegmentProbe
from hls_doctor.adapters.hlsjs.locate_player_probe import locate_player_probe
from hls_doctor.adapters.hlsjs.player_probe_report import PlayerProbeReport
from hls_doctor.adapters.hlsjs.run_player_probe import run_player_probe as run_harness
from hls_doctor.adapters.http.classify_http_error import require_usable_entry_url
from hls_doctor.adapters.http.guard_fetch_target import guard_fetch_target
from hls_doctor.domain.correlate.finding_model import Finding
from hls_doctor.settings.runtime_settings import HlsDoctorSettings
from hls_doctor.tool_surface.create_inspection_tools import resolve_default_url
from hls_doctor.workflows.build_probe_context import build_probe_context
from hls_doctor.workflows.probe_media_samples import run_media_probe
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
        """Probe one segment or init section with ffprobe: streams, format, timestamps.

        The bytes are downloaded through the guarded fetcher and probed as a
        local file, so ffprobe never fetches the network itself.
        """
        if not settings.demo:
            guard_fetch_target(url, allow_private=settings.hls_allow_private_targets)
        else:
            require_usable_entry_url(url)
        context = build_probe_context(settings)
        probe = context.media_probe()
        if probe is None:
            raise ToolFailure(
                FailureKind.INVALID_REQUEST,
                "Media probing is unavailable: ffprobe is not installed, or this demo"
                " scenario records no media output.",
                "Install FFmpeg, or pick a scenario with recorded ffprobe output.",
            )
        return run_media_probe(url, probe, context)

    def run_apple_validator(url: str = "") -> ValidatorReport:
        """Run Apple's mediastreamvalidator as an independent conformance crosscheck.

        The validator is a separate binary that fetches the stream itself: its
        requests do not pass this sample's SSRF guard (only the entry URL is
        checked). It is intended for operator machines, not deployed runtimes,
        and the deployed image does not ship it.
        """
        if not settings.demo:
            guard_fetch_target(
                resolve_default_url(url, settings),
                allow_private=settings.hls_allow_private_targets,
            )
        context = build_probe_context(settings)
        if context.validator is None:
            raise ToolFailure(
                FailureKind.INVALID_REQUEST,
                "No validator is available in this mode.",
                "Install Apple's HLS Tools (macOS) to run the crosscheck.",
            )
        return context.validator(resolve_default_url(url, settings))

    def run_player_probe(url: str, duration_seconds: float = 10) -> PlayerProbeReport:
        """Play the stream headlessly with hls.js and report its events and errors.

        Optional: needs Node.js 20+ and `npm install` in samples/hls-doctor/player-probe.
        The browser fetches the stream itself: its requests do not pass this
        sample's SSRF guard (only the entry URL is checked). Operator machines
        only; the deployed image does not ship Node.
        """
        guard_fetch_target(url, allow_private=settings.hls_allow_private_targets)
        return run_harness(url, duration_seconds)

    tools: list[ReadTool] = [watch_playlist, probe_segment, run_apple_validator]
    if player_probe_available():
        tools.append(run_player_probe)
    return tools


def player_probe_available() -> bool:
    """The hls.js harness tool is advertised only where it can actually run."""
    try:
        locate_player_probe()
    except ToolFailure:
        return False
    return True
