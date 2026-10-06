"""The read-only inspection tools shared by the MCP server and the hub pack."""

from pydantic import BaseModel, Field

from hls_doctor.adapters.http.classify_http_error import require_usable_entry_url
from hls_doctor.adapters.http.http_exchange import HttpExchange
from hls_doctor.adapters.http.redact_url import redact_url
from hls_doctor.domain.evidence.evidence_store import EvidenceStore
from hls_doctor.domain.graph.build_presentation_graph import build_presentation_graph
from hls_doctor.domain.graph.classify_presentation import (
    PresentationProfile,
    classify_presentation,
)
from hls_doctor.domain.graph.presentation_node import PresentationNode
from hls_doctor.domain.playlist.parse_media_playlist import parse_media_playlist
from hls_doctor.domain.playlist.parse_multivariant import parse_multivariant
from hls_doctor.domain.playlist.tokenize_playlist import tokenize_playlist
from hls_doctor.domain.report.report_model import InspectionReport
from hls_doctor.settings.runtime_settings import HlsDoctorSettings
from hls_doctor.workflows.build_probe_context import build_probe_context
from hls_doctor.workflows.inspect_stream import inspect_stream as run_inspection
from media_ops_contracts.domain_pack import ReadTool
from media_ops_contracts.load_fixture import load_fixture
from media_ops_contracts.tool_failure import FailureKind, ToolFailure


class ManifestFetch(BaseModel):
    url: str
    status: int | None
    content_type: str | None
    looks_like_m3u8: bool
    playlist_kind: str
    first_lines: list[str] = Field(default_factory=list)


class PlaylistSummary(BaseModel):
    url: str
    playlist_kind: str
    version: int | None = None
    variant_count: int = 0
    rendition_count: int = 0
    segment_count: int = 0
    target_duration: int | None = None
    media_sequence: int | None = None
    endlist: bool = False
    unknown_tag_lines: list[int] = Field(default_factory=list)


class PresentationMap(BaseModel):
    entry_url: str
    profile: PresentationProfile
    nodes: list[PresentationNode] = Field(default_factory=list)


def create_inspection_tools(settings: HlsDoctorSettings) -> list[ReadTool]:
    """Each tool builds a fresh probe context, so DEMO replay applies per call."""

    def fetch_manifest(url: str = "") -> ManifestFetch:
        """Fetch a playlist URL and say whether the response is plausibly M3U8.

        In demo mode an empty url defaults to the scenario's entry manifest.
        """
        url = resolve_default_url(url, settings)
        exchange = build_probe_context(settings).fetch(url)
        body = exchange.body_text or ""
        lines = tokenize_playlist(body)
        return ManifestFetch(
            url=redact_url(exchange.url),
            status=exchange.status,
            content_type=exchange.header("content-type"),
            looks_like_m3u8=body.lstrip().startswith("#EXTM3U"),
            playlist_kind=playlist_kind(body),
            first_lines=[line.raw for line in lines[:8]],
        )

    def parse_playlist(url: str) -> PlaylistSummary:
        """Fetch and parse one playlist; report structure counts and unknown tags."""
        require_usable_entry_url(url)
        exchange = build_probe_context(settings).fetch(url)
        body = exchange.body_text or ""
        lines = tokenize_playlist(body)
        kind = playlist_kind(body)
        summary = PlaylistSummary(url=exchange.url, playlist_kind=kind)
        if kind == "multivariant":
            parsed = parse_multivariant(lines)
            summary.version = parsed.version
            summary.variant_count = len(parsed.variants)
            summary.rendition_count = len(parsed.renditions)
            summary.unknown_tag_lines = parsed.unknown_tag_lines
        else:
            media = parse_media_playlist(lines)
            summary.version = media.version
            summary.segment_count = len(media.segments)
            summary.target_duration = media.target_duration
            summary.media_sequence = media.media_sequence
            summary.endlist = media.endlist
            summary.unknown_tag_lines = media.unknown_tag_lines
        return summary

    def map_presentation(url: str) -> PresentationMap:
        """Resolve every playlist beneath the entry URL into a presentation graph."""
        require_usable_entry_url(url)
        context = build_probe_context(settings)
        graph = build_presentation_graph(url, context.fetch, EvidenceStore())
        return PresentationMap(
            entry_url=url,
            profile=classify_presentation(graph),
            nodes=list(graph.nodes.values()),
        )

    def probe_http(url: str, include_body_bytes: int = 1024) -> HttpExchange:
        """One GET with timings and headers; an error status is evidence, not failure.

        The response is sanitized: query values redacted, headers allowlisted,
        and the body returned as a preview of at most `include_body_bytes`
        (capped at 65536) with its sha256.
        """
        require_usable_entry_url(url)
        preview = max(0, min(include_body_bytes, 65536))
        return build_probe_context(settings).fetch(url).sanitized(preview)

    def inspect_stream(url: str = "") -> InspectionReport:
        """Run the full inspection: graph, validation, delivery probes, findings.

        In demo mode an empty url defaults to the scenario's entry manifest.
        """
        return run_inspection(resolve_default_url(url, settings), build_probe_context(settings))

    return [fetch_manifest, parse_playlist, map_presentation, probe_http, inspect_stream]


def resolve_default_url(url: str, settings: HlsDoctorSettings) -> str:
    """An explicit URL, or the demo scenario's recorded entry point."""
    if url:
        require_usable_entry_url(url)
        return url
    if settings.demo:
        fixture = load_fixture(settings.fixtures_dir, settings.demo_scenario, "http.exchanges")
        return str(fixture.get("base_url", ""))
    raise ToolFailure(
        FailureKind.INVALID_REQUEST,
        "No URL was given.",
        "Pass the manifest URL, or set DEMO=1 to use the recorded scenario.",
    )


def playlist_kind(body: str) -> str:
    if "#EXT-X-STREAM-INF" in body or "#EXT-X-I-FRAME-STREAM-INF" in body:
        return "multivariant"
    if "#EXTINF" in body or "#EXT-X-TARGETDURATION" in body:
        return "media"
    return "unknown"
