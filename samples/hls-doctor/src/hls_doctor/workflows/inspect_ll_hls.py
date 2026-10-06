"""Active LL-HLS probes: blocking reload, rendition reports, preload hints (§15)."""

from hls_doctor.domain.correlate.finding_model import Finding, create_finding, observe
from hls_doctor.domain.correlate.severity_model import Confidence, Severity
from hls_doctor.domain.evidence.evidence_store import EvidenceStore
from hls_doctor.domain.graph.build_presentation_graph import (
    ParsedPlaylist,
    PresentationGraph,
)
from hls_doctor.domain.playlist.parse_media_playlist import parse_media_playlist
from hls_doctor.domain.playlist.resolve_uri import resolve_uri
from hls_doctor.domain.playlist.tokenize_playlist import tokenize_playlist
from hls_doctor.domain.validate.validate_ll_hls import is_low_latency
from hls_doctor.workflows.build_probe_context import ProbeContext

MAX_RENDITION_REPORT_LAG = 3


def inspect_ll_hls(
    graph: PresentationGraph, context: ProbeContext, evidence: EvidenceStore
) -> list[Finding]:
    findings: list[Finding] = []
    for parsed in graph.media_playlists():
        if parsed.media is None or not is_low_latency(parsed.media):
            continue
        probe_blocking_reload(parsed, context, evidence, findings)
        check_rendition_reports(parsed, graph, findings)
        probe_preload_hint(parsed, context, evidence, findings)
    return findings


def probe_blocking_reload(
    parsed: ParsedPlaylist,
    context: ProbeContext,
    evidence: EvidenceStore,
    findings: list[Finding],
) -> None:
    """Request the next MSN with _HLS_msn; the response must contain it."""
    media = parsed.media
    if media is None or not media.segments:
        return
    next_msn = media.segments[-1].media_sequence_number + 1
    url = f"{parsed.url}{'&' if '?' in parsed.url else '?'}_HLS_msn={next_msn}"
    exchange = context.fetch(url)
    evidence_id = evidence.record_exchange(exchange)
    if not exchange.ok or exchange.body_text is None:
        return
    blocked = parse_media_playlist(tokenize_playlist(exchange.body_text))
    newest = blocked.segments[-1].media_sequence_number if blocked.segments else None
    if newest is None or newest < next_msn:
        findings.append(
            create_finding(
                "Blocking playlist reload returns a stale generation",
                Severity.ERROR,
                Confidence.HIGH,
                "ll-hls",
                [parsed.url],
                [
                    observe(
                        f"_HLS_msn={next_msn} answered with newest MSN {newest} at"
                        f" +{exchange.at_ms} ms instead of blocking until it exists",
                        evidence_id,
                    )
                ],
                "The server (or a CDN in front of it) ignores the delivery directive.",
                "Low-latency clients spin on stale playlists and fall off the edge.",
                likely_causes=[
                    "CDN strips or caches _HLS_msn requests",
                    "origin does not implement blocking reload",
                ],
                next_probe="Send the same directive straight to the origin.",
            )  # fmt: skip
        )


def check_rendition_reports(
    parsed: ParsedPlaylist, graph: PresentationGraph, findings: list[Finding]
) -> None:
    media = parsed.media
    if media is None:
        return
    for report in media.rendition_reports:
        if report.uri is None or report.last_msn is None:
            continue
        peer_url = resolve_uri(report.uri, parsed.url)
        peer = graph.playlists.get(peer_url)
        if peer is None or peer.media is None or not peer.media.segments:
            continue
        actual = peer.media.segments[-1].media_sequence_number
        lag = actual - report.last_msn
        if lag > MAX_RENDITION_REPORT_LAG:
            findings.append(
                create_finding(
                    "Stale rendition report",
                    Severity.WARNING,
                    Confidence.HIGH,
                    "ll-hls",
                    [parsed.url],
                    [
                        observe(
                            f"RENDITION-REPORT for {report.uri!r} says LAST-MSN="
                            f"{report.last_msn} while that rendition is at MSN {actual}"
                            f" ({lag} segments ahead)"
                        )
                    ],
                    "Rendition reports must track their rendition's live edge.",
                    "Fast ABR switches land behind the edge and stall.",
                )  # fmt: skip
            )


def probe_preload_hint(
    parsed: ParsedPlaylist,
    context: ProbeContext,
    evidence: EvidenceStore,
    findings: list[Finding],
) -> None:
    media = parsed.media
    if media is None:
        return
    for hint in media.preload_hints:
        if hint.uri is None:
            continue
        url = resolve_uri(hint.uri, parsed.url)
        observations = []
        resolved = False
        for delay in (0.0, 1.0, 2.0):
            if delay:
                context.wait(delay)
            exchange = context.fetch(url)
            evidence_id = evidence.record_exchange(exchange)
            observations.append(
                observe(
                    f"Hinted object returned HTTP {exchange.status} at +{exchange.at_ms} ms",
                    evidence_id,
                )  # fmt: skip
            )
            if exchange.ok:
                resolved = True
                break
        if not resolved:
            findings.append(
                create_finding(
                    "PRELOAD-HINT never resolves",
                    Severity.WARNING,
                    Confidence.HIGH,
                    "ll-hls",
                    [url],
                    observations,
                    "A hinted part may briefly 404, but it must appear promptly;"
                    " this one never did within the probe window.",
                    "Clients that request hints early waste connections and can"
                    " mis-pace the live edge; this is not a generic missing segment.",
                    next_probe="Watch longer to see whether the hint ever materializes.",
                )  # fmt: skip
            )
