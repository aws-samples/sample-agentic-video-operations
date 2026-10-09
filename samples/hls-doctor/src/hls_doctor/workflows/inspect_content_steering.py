"""Fetch and judge Content Steering: manifest, pathways, per-pathway health (§16)."""

import json

from hls_doctor.domain.correlate.finding_model import Finding, create_finding, observe
from hls_doctor.domain.correlate.severity_model import Confidence, Severity
from hls_doctor.domain.evidence.evidence_store import EvidenceStore
from hls_doctor.domain.graph.build_presentation_graph import PresentationGraph
from hls_doctor.domain.playlist.resolve_uri import resolve_uri
from hls_doctor.domain.validate.validate_steering import validate_steering_manifest
from hls_doctor.workflows.build_probe_context import ProbeContext


def inspect_content_steering(
    graph: PresentationGraph, context: ProbeContext, evidence: EvidenceStore
) -> list[Finding]:
    entry = graph.multivariant
    if entry is None or entry.multivariant is None or entry.multivariant.steering is None:
        return []
    steering = entry.multivariant.steering
    if not steering.server_uri:
        return []
    url = resolve_uri(steering.server_uri, entry.url)
    exchange = context.fetch(url)
    evidence_id = evidence.record_exchange(exchange)
    if not exchange.ok:
        return [
            create_finding(
                "Steering manifest is unreachable",
                Severity.WARNING,
                Confidence.CONFIRMED,
                "content-steering",
                [url],
                [observe(f"SERVER-URI returned HTTP {exchange.status}", evidence_id)],
                "Clients fall back to the playlist's default pathway order.",
                "Steering-based failover and load distribution are inactive.",
            )  # fmt: skip
        ]
    try:
        payload = json.loads(exchange.body_text or "")
    except json.JSONDecodeError:
        payload = None
    findings = validate_steering_manifest(url, payload, entry.multivariant)
    findings.extend(probe_pathways(graph, context, evidence))
    return findings


def probe_pathways(
    graph: PresentationGraph, context: ProbeContext, evidence: EvidenceStore
) -> list[Finding]:
    """One representative probe per pathway; a failed pathway with a healthy
    alternative is a warning, never a fatal presentation failure."""
    entry = graph.multivariant
    if entry is None or entry.multivariant is None:
        return []
    health: dict[str, tuple[bool, str, str]] = {}
    for variant in entry.multivariant.variants:
        pathway = variant.pathway_id or "."
        if pathway in health or variant.iframe_only:
            continue
        url = resolve_uri(variant.uri, entry.url)
        exchange = context.fetch(url)
        evidence_id = evidence.record_exchange(exchange)
        health[pathway] = (exchange.ok, url, evidence_id)
    failed = {k: v for k, v in health.items() if not v[0]}
    if not failed or len(failed) == len(health):
        return []  # total failure surfaces through the delivery findings instead
    healthy = sorted(set(health) - set(failed))
    return [
        create_finding(
            f"Steering pathway {pathway!r} is failing while {', '.join(healthy)} serves",
            Severity.WARNING,
            Confidence.HIGH,
            "content-steering",
            [url],
            [observe("The pathway's representative variant failed its probe", eid)],
            "One pathway is down; steering can keep clients on the healthy one.",
            "Capacity and geography shrink to the surviving pathway; no outage"
            " as long as steering moves clients.",
            next_probe="Probe more variants of the failing pathway to size the impact.",
        )  # fmt: skip
        for pathway, (_, url, eid) in failed.items()
    ]
