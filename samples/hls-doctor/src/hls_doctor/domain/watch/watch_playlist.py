"""Reload a Media Playlist over a bounded window, probing newly advertised segments."""

from collections.abc import Callable

from pydantic import BaseModel, Field

from hls_doctor.adapters.http.http_exchange import FetchUrl
from hls_doctor.domain.evidence.evidence_store import EvidenceStore
from hls_doctor.domain.playlist.parse_media_playlist import parse_media_playlist
from hls_doctor.domain.playlist.resolve_uri import resolve_uri
from hls_doctor.domain.playlist.tokenize_playlist import tokenize_playlist
from hls_doctor.domain.watch.playlist_snapshot import PlaylistSnapshot, build_snapshot

SEGMENT_RETRY_DELAYS_SECONDS = (0.3, 1.0)


class WatchResult(BaseModel):
    url: str
    snapshots: list[PlaylistSnapshot] = Field(default_factory=list)
    probed_segment_urls: list[str] = Field(default_factory=list)


def watch_playlist(
    url: str,
    *,
    fetch: FetchUrl,
    evidence: EvidenceStore,
    now_ms: Callable[[], int],
    wait: Callable[[float], None],
    duration_seconds: float,
    poll_interval_seconds: float = 2.0,
) -> WatchResult:
    """Reload until the window closes; probe each newly advertised segment with retries."""
    result = WatchResult(url=url)
    seen_msns: set[int] = set()
    deadline = now_ms() + int(duration_seconds * 1000)
    while True:
        snapshot = observe_once(url, fetch, evidence, now_ms)
        if snapshot is not None:
            probe_new_segments(url, snapshot, seen_msns, fetch, evidence, wait, result)
            result.snapshots.append(snapshot)
        if now_ms() + int(poll_interval_seconds * 1000) > deadline:
            return result
        wait(poll_interval_seconds)


def observe_once(
    url: str,
    fetch: FetchUrl,
    evidence: EvidenceStore,
    now_ms: Callable[[], int],
) -> PlaylistSnapshot | None:
    exchange = fetch(url)
    evidence_id = evidence.record_exchange(exchange)
    if not exchange.ok or exchange.body_text is None:
        return None
    media = parse_media_playlist(tokenize_playlist(exchange.body_text))
    return build_snapshot(
        url, now_ms(), evidence_id, media,
        exchange.header("etag"), exchange.header("age"),
    )  # fmt: skip


def probe_new_segments(
    base_url: str,
    snapshot: PlaylistSnapshot,
    seen_msns: set[int],
    fetch: FetchUrl,
    evidence: EvidenceStore,
    wait: Callable[[float], None],
    result: WatchResult,
) -> None:
    """Probe segments advertised for the first time; retry failures briefly."""
    if snapshot.newest_msn is None or snapshot.newest_uri is None:
        return
    if not seen_msns:
        seen_msns.update(snapshot.advertised_msns)
        return
    if snapshot.newest_msn in seen_msns:
        return
    seen_msns.update(snapshot.advertised_msns)
    segment_url = resolve_uri(snapshot.newest_uri, base_url)
    result.probed_segment_urls.append(segment_url)
    exchange = fetch(segment_url)
    evidence.record_exchange(exchange)
    for delay in SEGMENT_RETRY_DELAYS_SECONDS:
        if exchange.ok:
            return
        wait(delay)
        exchange = fetch(segment_url)
        evidence.record_exchange(exchange)
