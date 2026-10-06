"""Probe representative resources beneath each media playlist (spec §19 default)."""

from hls_doctor.adapters.http.http_exchange import FetchUrl
from hls_doctor.domain.evidence.evidence_store import EvidenceStore
from hls_doctor.domain.graph.build_presentation_graph import ParsedPlaylist, PresentationGraph
from hls_doctor.domain.playlist.media_playlist_model import MediaSegment
from hls_doctor.domain.playlist.resolve_uri import resolve_uri

SEGMENT_SAMPLE_COUNT = 3


class SamplePlan:
    """URLs to probe, with the node type and GAP marking needed for findings."""

    def __init__(self) -> None:
        self.resource_types: dict[str, str] = {}
        self.gap_urls: set[str] = set()

    def add(self, url: str, resource_type: str, *, gap: bool = False) -> None:
        self.resource_types.setdefault(url, resource_type)
        if gap:
            self.gap_urls.add(url)


def plan_default_samples(graph: PresentationGraph) -> SamplePlan:
    plan = SamplePlan()
    for parsed in graph.media_playlists():
        collect_playlist_samples(parsed, plan)
    return plan


def collect_playlist_samples(parsed: ParsedPlaylist, plan: SamplePlan) -> None:
    media = parsed.media
    if media is None:
        return
    for segment in sampled_segments(media.segments):
        plan.add(resolve_uri(segment.uri, parsed.url), "segment", gap=segment.gap)
    for segment in media.segments:
        if segment.segment_map and segment.segment_map.uri:
            plan.add(resolve_uri(segment.segment_map.uri, parsed.url), "init_section")
        if segment.key and segment.key.uri and segment.key.method != "NONE":
            plan.add(resolve_uri(segment.key.uri, parsed.url), "key")


def sampled_segments(segments: list[MediaSegment]) -> list[MediaSegment]:
    if len(segments) <= 2 * SEGMENT_SAMPLE_COUNT:
        return segments
    return segments[:SEGMENT_SAMPLE_COUNT] + segments[-SEGMENT_SAMPLE_COUNT:]


def probe_samples(plan: SamplePlan, fetch: FetchUrl, evidence: EvidenceStore) -> None:
    for url in plan.resource_types:
        exchange = fetch(url)
        evidence.record_exchange(exchange)
