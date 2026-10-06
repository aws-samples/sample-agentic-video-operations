"""Watch the live playlists of a presentation and correlate what the window shows."""

from pydantic import BaseModel, Field

from hls_doctor.adapters.http.classify_http_error import require_usable_entry_url
from hls_doctor.domain.correlate.correlate_findings import correlate_findings
from hls_doctor.domain.correlate.correlation_rules import detect_publication_races
from hls_doctor.domain.correlate.finding_model import Finding
from hls_doctor.domain.evidence.evidence_store import EvidenceStore
from hls_doctor.domain.graph.build_presentation_graph import (
    PresentationGraph,
    build_presentation_graph,
)
from hls_doctor.domain.watch.detect_live_defects import detect_live_defects
from hls_doctor.domain.watch.watch_playlist import WatchResult, watch_playlist
from hls_doctor.workflows.build_probe_context import ProbeContext

MAX_WATCHED_RENDITIONS = 4


class WatchReport(BaseModel):
    entry_url: str
    watched_playlists: list[str] = Field(default_factory=list)
    reloads_per_playlist: dict[str, int] = Field(default_factory=dict)
    findings: list[Finding] = Field(default_factory=list)
    evidence: EvidenceStore = Field(default_factory=EvidenceStore)


def watch_stream(
    entry_url: str,
    context: ProbeContext,
    *,
    duration_seconds: float | None = None,
) -> WatchReport:
    """Observe the live playlists over a bounded window (spec §9)."""
    require_usable_entry_url(entry_url)
    evidence = EvidenceStore()
    graph = build_presentation_graph(entry_url, context.fetch, evidence)
    watches, findings = watch_media_playlists(
        graph, context, evidence, bounded_duration(duration_seconds, context)
    )
    ranked = correlate_findings(findings)
    return WatchReport(
        entry_url=entry_url,
        watched_playlists=[watch.url for watch in watches],
        reloads_per_playlist={watch.url: len(watch.snapshots) for watch in watches},
        findings=ranked,
        evidence=evidence,
    )


def watch_media_playlists(
    graph: PresentationGraph,
    context: ProbeContext,
    evidence: EvidenceStore,
    window_seconds: float,
) -> tuple[list[WatchResult], list[list[Finding]]]:
    """Watch every live media playlist of an already-built graph."""
    watches: list[WatchResult] = []
    findings: list[list[Finding]] = []
    for parsed in graph.media_playlists()[:MAX_WATCHED_RENDITIONS]:
        if parsed.media is None or parsed.media.endlist:
            continue
        watch = watch_playlist(
            parsed.url,
            fetch=context.fetch,
            evidence=evidence,
            now_ms=context.now_ms,
            wait=context.wait,
            duration_seconds=window_seconds,
        )
        watches.append(watch)
        findings.append(
            detect_live_defects(parsed.url, watch.snapshots, parsed.media.target_duration)
        )
    findings.append(detect_publication_races(evidence, watches))
    return watches, findings


def bounded_duration(duration_seconds: float | None, context: ProbeContext) -> float:
    maximum = float(context.settings.hls_max_watch_seconds)
    if duration_seconds is None:
        return 10.0 if context.demo else min(20.0, maximum)
    return min(duration_seconds, maximum)
