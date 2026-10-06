"""Analysis tools: SCTE-35 decoding, interstitial deep-dive, rendition alignment."""

from pydantic import BaseModel, Field

from hls_doctor.domain.align.compare_renditions import compare_renditions
from hls_doctor.domain.align.match_rendition_positions import read_position
from hls_doctor.domain.correlate.correlate_findings import correlate_findings
from hls_doctor.domain.correlate.finding_model import Finding
from hls_doctor.domain.evidence.evidence_store import EvidenceStore
from hls_doctor.domain.graph.build_presentation_graph import (
    PresentationGraph,
    build_presentation_graph,
)
from hls_doctor.domain.scte35.decode_splice_info import decode_splice_info
from hls_doctor.domain.scte35.splice_model import SpliceInfoSection
from hls_doctor.settings.runtime_settings import HlsDoctorSettings
from hls_doctor.tool_surface.create_inspection_tools import resolve_default_url
from hls_doctor.workflows.build_probe_context import build_probe_context
from hls_doctor.workflows.inspect_interstitial import inspect_interstitials
from media_ops_contracts.domain_pack import ReadTool


class AlignmentReport(BaseModel):
    entry_url: str
    compared_renditions: list[str] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)


class InterstitialReport(BaseModel):
    entry_url: str
    findings: list[Finding] = Field(default_factory=list)


def create_analysis_tools(settings: HlsDoctorSettings) -> list[ReadTool]:
    """Each tool builds a fresh probe context, so DEMO replay applies per call."""

    def decode_scte35(payload: str) -> SpliceInfoSection:
        """Decode a base64 or 0x-hex SCTE-35 payload into its splice structures."""
        return decode_splice_info(payload)

    def compare_rendition_alignment(url: str = "") -> AlignmentReport:
        """Compare sequence position, program clock and events across renditions."""
        entry = resolve_default_url(url, settings)
        context = build_probe_context(settings)
        graph = build_presentation_graph(entry, context.fetch, EvidenceStore())
        positions = [
            read_position(parsed.url, role_of(graph, parsed.url), parsed.media)
            for parsed in graph.media_playlists()
            if parsed.media is not None
        ]
        return AlignmentReport(
            entry_url=entry,
            compared_renditions=[position.url for position in positions],
            findings=correlate_findings([compare_renditions(positions)]),
        )

    def inspect_interstitial(url: str = "") -> InterstitialReport:
        """Validate and probe every interstitial event: asset lists, assets, codecs."""
        entry = resolve_default_url(url, settings)
        context = build_probe_context(settings)
        evidence = EvidenceStore()
        graph = build_presentation_graph(entry, context.fetch, evidence)
        findings = correlate_findings([inspect_interstitials(graph, context, evidence)])
        return InterstitialReport(entry_url=entry, findings=findings)

    return [decode_scte35, compare_rendition_alignment, inspect_interstitial]


def role_of(graph: PresentationGraph, url: str) -> str:
    node = graph.nodes.get(url)
    return str(node.role) if node is not None and node.role else "video"
