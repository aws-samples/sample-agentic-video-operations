"""Probe representative segment media with ffprobe and derive media findings."""

from hls_doctor.adapters.ffprobe.probe_report import SegmentProbe
from hls_doctor.domain.correlate.finding_model import Finding
from hls_doctor.domain.evidence.evidence_store import EvidenceStore
from hls_doctor.domain.graph.build_presentation_graph import PresentationGraph
from hls_doctor.domain.media.detect_media_defects import detect_media_defects
from hls_doctor.domain.playlist.resolve_uri import resolve_uri
from hls_doctor.workflows.build_probe_context import ProbeContext
from media_ops_contracts.tool_failure import ToolFailure

MAX_MEDIA_PROBES_PER_PLAYLIST = 2


def media_findings(
    graph: PresentationGraph, context: ProbeContext, evidence: EvidenceStore
) -> list[Finding]:
    """Media probing degrades gracefully: no ffprobe (or no recording) means no probes."""
    probe = context.media_probe()
    if probe is None:
        return []
    findings = []
    for parsed in graph.media_playlists():
        if parsed.media is None or not parsed.media.segments:
            continue
        probes: list[SegmentProbe] = []
        targets = [parsed.media.segments[0], parsed.media.segments[-1]]
        for segment in targets[:MAX_MEDIA_PROBES_PER_PLAYLIST]:
            url = resolve_uri(segment.uri, parsed.url)
            try:
                result = probe(url, with_packets=True)
            except ToolFailure:
                continue  # this scenario or stream records no media for this URL
            evidence.record_tool_run("ffprobe", url, summarize_probe(result))
            probes.append(result)
        discontinuity_present = any(s.discontinuity for s in parsed.media.segments)
        findings.extend(detect_media_defects(probes, discontinuity_present=discontinuity_present))
    return findings


def summarize_probe(result: SegmentProbe) -> str:
    if not result.available:
        return f"unavailable: {result.unavailable_reason}"
    kinds = ", ".join(f"{stream.codec_type}:{stream.codec_name}" for stream in result.streams)
    return f"{len(result.packets)} packets; streams: {kinds or 'none'}"
