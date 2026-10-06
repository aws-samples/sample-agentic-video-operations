"""Record a live HLS presentation into an HLS Doctor replay fixture.

Crawls the presentation graph, probes the resources the inspector samples, and
writes fixtures/<scenario>/http.exchanges.json with redaction built in: hosts
are rewritten to demo.example, credential-shaped query values are stripped, and
media bodies are truncated stubs. Playlist text is kept verbatim (minus host).

Usage:
    uv run python scripts/record_hls_fixtures.py <url> --scenario <name> \
        [--reloads N] [--interval SECONDS]

Record only streams you are licensed to redistribute as fixtures.
"""

import argparse
import base64
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "fixtures"
PLACEHOLDER_HOST = "demo.example"
MEDIA_STUB_BYTES = 1024


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Entry manifest URL to record")
    parser.add_argument("--scenario", required=True, help="Output scenario name")
    parser.add_argument("--reloads", type=int, default=0, help="Media playlist reloads")
    parser.add_argument("--interval", type=float, default=2.0, help="Seconds between reloads")
    arguments = parser.parse_args()

    from hls_doctor.adapters.http.fetch_url import create_live_fetch
    from hls_doctor.domain.evidence.evidence_store import EvidenceStore
    from hls_doctor.domain.graph.build_presentation_graph import build_presentation_graph
    from hls_doctor.workflows.probe_segment_samples import plan_default_samples

    fetch = create_live_fetch(timeout_seconds=15, user_agent="hls-doctor-recorder/0.1")
    evidence = EvidenceStore()
    graph = build_presentation_graph(arguments.url, fetch, evidence)
    plan = plan_default_samples(graph)

    recorder = FixtureRecorder(urlsplit(arguments.url))
    for parsed in graph.playlists.values():
        recorder.add(parsed.url, parsed.exchange.model_dump())
    for url in plan.resource_types:
        recorder.add(url, fetch(url).model_dump())
    for _ in range(arguments.reloads):
        time.sleep(arguments.interval)
        for parsed in graph.media_playlists():
            recorder.add(parsed.url, fetch(parsed.url).model_dump())

    out_dir = FIXTURES / arguments.scenario
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "http.exchanges.json"
    path.write_text(json.dumps(recorder.build(arguments.url), indent=1) + "\n")
    print(f"Wrote {path} ({len(recorder.exchanges)} URLs)")
    return 0


class FixtureRecorder:
    """Accumulates exchanges per URL; repeats become ordered sequences."""

    def __init__(self, entry_parts: Any) -> None:
        self.entry_host = entry_parts.netloc
        self.exchanges: dict[str, list[dict[str, Any]]] = {}

    def add(self, url: str, observed: dict[str, Any]) -> None:
        entry = self.redact_entry(observed)
        self.exchanges.setdefault(self.redact_url(url), []).append(entry)

    def redact_url(self, url: str) -> str:
        parts = urlsplit(url)
        return parts._replace(netloc=PLACEHOLDER_HOST, query="").geturl()

    def redact_entry(self, observed: dict[str, Any]) -> dict[str, Any]:
        entry: dict[str, Any] = {"at_ms": observed["at_ms"], "status": observed["status"]}
        if observed.get("transport_error"):
            entry["transport_error"] = observed["transport_error"]
        entry["headers"] = {
            name: value
            for name, value in observed.get("headers", {}).items()
            if name.lower() not in ("set-cookie", "authorization")
        }
        body_text = observed.get("body_text")
        if body_text is not None:
            entry["body"] = body_text.replace(self.entry_host, PLACEHOLDER_HOST)
        elif observed.get("body_bytes_b64"):
            raw = base64.b64decode(observed["body_bytes_b64"])[:MEDIA_STUB_BYTES]
            entry["body_b64"] = base64.b64encode(raw).decode()
            entry["truncated"] = True
        for key in ("ttfb_ms", "total_ms"):
            if observed.get(key) is not None:
                entry[key] = round(observed[key], 1)
        return entry

    def build(self, entry_url: str) -> dict[str, Any]:
        exchanges: dict[str, Any] = {}
        for url, entries in self.exchanges.items():
            exchanges[url] = entries[0] if len(entries) == 1 else {"sequence": entries}
        return {"base_url": self.redact_url(entry_url), "exchanges": exchanges}


if __name__ == "__main__":
    raise SystemExit(main())
