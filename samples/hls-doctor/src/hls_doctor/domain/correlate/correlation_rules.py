"""Cross-evidence correlation rules (spec §10): patterns, not single failures."""

from hls_doctor.adapters.http.http_exchange import HttpExchange
from hls_doctor.domain.correlate.finding_model import (
    Finding,
    Observation,
    create_finding,
    observe,
)
from hls_doctor.domain.correlate.severity_model import Confidence, Severity
from hls_doctor.domain.evidence.evidence_store import EvidenceStore
from hls_doctor.domain.watch.watch_playlist import WatchResult


def detect_publication_races(evidence: EvidenceStore, watches: list[WatchResult]) -> list[Finding]:
    """A segment that 404s right after being advertised and then appears is a race."""
    raced: list[tuple[str, list[Observation], int]] = []
    for watch in watches:
        for url in watch.probed_segment_urls:
            observed = evidence.exchanges_for_url(url)
            race = classify_race(observed)
            if race is not None:
                raced.append((url, *race))
    if not raced:
        return []
    observations = [item for _, items, _ in raced for item in items]
    delays = [delay for _, _, delay in raced]
    confidence = Confidence.HIGH if len(raced) > 1 else Confidence.MEDIUM
    return [
        create_finding(
            "Segments are advertised before they are available",
            Severity.ERROR,
            confidence,
            "delivery",
            [url for url, _, _ in raced],
            observations,
            f"{len(raced)} newly advertised segment(s) returned 404 and became available"
            f" {min(delays) / 1000:.2f}-{max(delays) / 1000:.2f} s later: a publication"
            " race between the playlist and the media objects.",
            "Clients at the live edge hit 404s and stall or retry.",
            likely_causes=[
                "playlist published before the segment upload completes",
                "CDN edge receives the playlist before the object propagates",
            ],
            next_probe="Compare origin availability time with CDN edge availability.",
        )  # fmt: skip
    ]


def classify_race(
    observed: list[tuple[str, HttpExchange]],
) -> tuple[list[Observation], int] | None:
    """Observations and the availability delay, when failures resolve into a 200."""
    failures = [(eid, ex) for eid, ex in observed if not ex.ok]
    successes = [(eid, ex) for eid, ex in observed if ex.ok]
    if not failures or not successes:
        return None
    first_failure = min(failures, key=lambda item: item[1].at_ms)
    first_success = min(successes, key=lambda item: item[1].at_ms)
    if first_success[1].at_ms <= first_failure[1].at_ms:
        return None
    observations = [
        observe(f"Returned HTTP {exchange.status} at +{exchange.at_ms} ms", evidence_id)
        for evidence_id, exchange in sorted(observed, key=lambda item: item[1].at_ms)
    ]
    return observations, first_success[1].at_ms - first_failure[1].at_ms
