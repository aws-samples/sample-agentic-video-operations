"""Fixture-backed fetch with a shared virtual clock, for deterministic replay.

Fixture shape (fixtures/<scenario>/http.exchanges.json):
  {"base_url": "...",
   "exchanges": {"<url>": {"status": ..., "headers": {...}, "body": "..."}
                 | {"sequence": [{"at_ms": 0, ...}, ...]}
                 | {"transport_error": "ConnectTimeout"}}}
A sequence advances one entry per request and clamps at the last entry.
"""

from pathlib import Path
from typing import Any

from hls_doctor.adapters.http.classify_http_error import missing_fixture_exchange
from hls_doctor.adapters.http.http_exchange import FetchUrl, HttpExchange
from media_ops_contracts.load_fixture import load_fixture


class ReplayTimeline:
    """Virtual clock shared by replayed fetch, watch waits and reports."""

    def __init__(self) -> None:
        self.now_ms = 0

    def advance_to(self, at_ms: int) -> None:
        self.now_ms = max(self.now_ms, at_ms)

    def wait(self, seconds: float) -> None:
        self.now_ms += int(seconds * 1000)


def create_replay_fetch(fixtures_dir: Path, scenario: str, timeline: ReplayTimeline) -> FetchUrl:
    """A FetchUrl answering from the scenario's recorded exchanges. Fails closed."""
    fixture = load_fixture(fixtures_dir, scenario, "http.exchanges")
    exchanges: dict[str, Any] = fixture.get("exchanges", {})
    cursors: dict[str, int] = {}

    def fetch(url: str, *, range_header: str | None = None) -> HttpExchange:
        recorded = exchanges.get(url)
        if recorded is None:
            raise missing_fixture_exchange(url, scenario)
        entry = next_entry(recorded, url)
        timeline.advance_to(int(entry.get("at_ms", timeline.now_ms)))
        return build_replayed_exchange(url, entry, timeline.now_ms)

    def next_entry(recorded: dict[str, Any], url: str) -> dict[str, Any]:
        sequence = recorded.get("sequence")
        if sequence is None:
            return recorded
        position = min(cursors.get(url, 0), len(sequence) - 1)
        cursors[url] = position + 1
        entry: dict[str, Any] = sequence[position]
        return entry

    return fetch


def build_replayed_exchange(url: str, entry: dict[str, Any], now_ms: int) -> HttpExchange:
    return HttpExchange(
        url=entry.get("final_url", url),
        requested_url=url,
        at_ms=now_ms,
        status=entry.get("status"),
        transport_error=entry.get("transport_error"),
        headers=entry.get("headers", {}),
        body_text=entry.get("body"),
        body_bytes_b64=entry.get("body_b64"),
        body_truncated=bool(entry.get("truncated", False)),
        content_length=entry.get("content_length"),
        ttfb_ms=entry.get("ttfb_ms"),
        total_ms=entry.get("total_ms"),
        redirects=entry.get("redirects", []),
    )
