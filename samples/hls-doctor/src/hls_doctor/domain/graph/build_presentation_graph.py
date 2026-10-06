"""Recursively resolve the presentation (spec §6C), recording every fetch as evidence."""

from pydantic import BaseModel, Field

from hls_doctor.adapters.http.http_exchange import FetchUrl, HttpExchange
from hls_doctor.domain.evidence.evidence_store import EvidenceStore
from hls_doctor.domain.graph.presentation_node import NodeRole, PresentationNode
from hls_doctor.domain.playlist.media_playlist_model import MediaPlaylist
from hls_doctor.domain.playlist.multivariant_model import MultivariantPlaylist, Rendition
from hls_doctor.domain.playlist.parse_media_playlist import parse_media_playlist
from hls_doctor.domain.playlist.parse_multivariant import parse_multivariant
from hls_doctor.domain.playlist.playlist_line import PlaylistLine
from hls_doctor.domain.playlist.resolve_uri import build_variable_table, resolve_uri
from hls_doctor.domain.playlist.tokenize_playlist import tokenize_playlist

MAX_MEDIA_PLAYLISTS = 40


class ParsedPlaylist(BaseModel):
    url: str
    lines: list[PlaylistLine]
    multivariant: MultivariantPlaylist | None = None
    media: MediaPlaylist | None = None
    exchange: HttpExchange


class PresentationGraph(BaseModel):
    entry_url: str
    nodes: dict[str, PresentationNode] = Field(default_factory=dict)
    playlists: dict[str, ParsedPlaylist] = Field(default_factory=dict)

    @property
    def multivariant(self) -> ParsedPlaylist | None:
        parsed = self.playlists.get(self.entry_url)
        return parsed if parsed and parsed.multivariant else None

    def media_playlists(self) -> list[ParsedPlaylist]:
        return [parsed for parsed in self.playlists.values() if parsed.media is not None]


def is_multivariant(lines: list[PlaylistLine]) -> bool:
    return any(
        line.name in ("EXT-X-STREAM-INF", "EXT-X-MEDIA", "EXT-X-I-FRAME-STREAM-INF")
        for line in lines
        if line.kind == "tag"
    ) and not any(line.name == "EXTINF" for line in lines if line.kind == "tag")


def build_presentation_graph(
    entry_url: str, fetch: FetchUrl, evidence: EvidenceStore
) -> PresentationGraph:
    """Fetch the entry playlist and every reachable playlist beneath it."""
    graph = PresentationGraph(entry_url=entry_url)
    entry = fetch_playlist(entry_url, "entry", None, fetch, evidence, graph)
    if entry is None or entry.multivariant is None:
        return graph
    variables = build_variable_table(entry.multivariant.defines, entry_url)
    walk_multivariant(entry.multivariant, entry_url, variables, fetch, evidence, graph)
    return graph


def walk_multivariant(
    multivariant: MultivariantPlaylist,
    base_url: str,
    variables: dict[str, str],
    fetch: FetchUrl,
    evidence: EvidenceStore,
    graph: PresentationGraph,
) -> None:
    for variant in multivariant.variants:
        if len(graph.playlists) > MAX_MEDIA_PLAYLISTS:
            return
        url = resolve_uri(variant.uri, base_url, variables)
        role: NodeRole = "iframe" if variant.iframe_only else "video"
        parsed = fetch_playlist(url, role, base_url, fetch, evidence, graph)
        if parsed is not None:
            node = graph.nodes[url]
            node.bandwidth = variant.bandwidth
            node.declared_at_line = variant.line_number
    for rendition in multivariant.renditions:
        if rendition.uri and len(graph.playlists) <= MAX_MEDIA_PLAYLISTS:
            url = resolve_uri(rendition.uri, base_url, variables)
            fetch_playlist(url, rendition_role(rendition), base_url, fetch, evidence, graph)
            annotate_rendition(graph.nodes[url], rendition)


def rendition_role(rendition: Rendition) -> NodeRole:
    role = rendition.media_type.lower().replace("_", "-")
    if role in ("audio", "subtitles", "closed-captions"):
        return role  # type: ignore[return-value]
    return "video"


def annotate_rendition(node: PresentationNode, rendition: Rendition) -> None:
    node.group_id = rendition.group_id
    node.name = rendition.name
    node.language = rendition.language
    node.declared_at_line = rendition.line_number


def fetch_playlist(
    url: str,
    role: NodeRole,
    parent_url: str | None,
    fetch: FetchUrl,
    evidence: EvidenceStore,
    graph: PresentationGraph,
) -> ParsedPlaylist | None:
    if url in graph.playlists:
        return graph.playlists[url]
    exchange = fetch(url)
    evidence_id = evidence.record_exchange(exchange)
    node = PresentationNode(
        url=url, node_type="media_playlist", role=role, parent_url=parent_url,
        evidence_ids=[evidence_id],
    )  # fmt: skip
    graph.nodes[url] = node
    if not exchange.ok or exchange.body_text is None:
        return None
    lines = tokenize_playlist(exchange.body_text)
    parsed = ParsedPlaylist(url=url, lines=lines, exchange=exchange)
    if is_multivariant(lines):
        node.node_type = "multivariant"
        parsed.multivariant = parse_multivariant(lines)
    else:
        parsed.media = parse_media_playlist(lines)
    graph.playlists[url] = parsed
    return parsed
