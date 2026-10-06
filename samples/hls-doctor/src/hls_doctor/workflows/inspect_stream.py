"""The full inspection pipeline: fetch, parse, validate, probe, correlate (spec §6)."""

from hls_doctor.adapters.http.classify_http_error import (
    entry_point_unreachable,
    require_usable_entry_url,
)
from hls_doctor.adapters.http.redact_url import redact_url
from hls_doctor.domain.correlate.correlate_findings import correlate_findings
from hls_doctor.domain.correlate.finding_model import Finding
from hls_doctor.domain.evidence.correlate_http_patterns import derive_unreachable_findings
from hls_doctor.domain.evidence.evidence_store import EvidenceStore
from hls_doctor.domain.graph.build_presentation_graph import (
    PresentationGraph,
    build_presentation_graph,
)
from hls_doctor.domain.graph.classify_presentation import classify_presentation
from hls_doctor.domain.report.report_model import InspectionReport
from hls_doctor.domain.report.summarize_presentation import (
    build_inventory,
    summarize_presentation,
)
from hls_doctor.domain.validate.validate_encryption import validate_encryption
from hls_doctor.domain.validate.validate_media_playlist import validate_media_playlist
from hls_doctor.domain.validate.validate_multivariant import validate_multivariant
from hls_doctor.domain.validate.validate_renditions import validate_renditions
from hls_doctor.domain.validate.validate_syntax import validate_syntax
from hls_doctor.domain.versioning.compute_required_version import (
    compute_version_findings,
    required_media_version,
    required_multivariant_version,
)
from hls_doctor.workflows.build_probe_context import ProbeContext
from hls_doctor.workflows.probe_media_samples import media_findings
from hls_doctor.workflows.probe_segment_samples import (
    SamplePlan,
    plan_default_samples,
    probe_samples,
)
from hls_doctor.workflows.run_validator_crosscheck import run_validator_crosscheck
from hls_doctor.workflows.watch_stream import watch_media_playlists


def inspect_stream(
    entry_url: str,
    context: ProbeContext,
    *,
    redact_all_query: bool = False,
    watch_seconds: float | None = None,
) -> InspectionReport:
    require_usable_entry_url(entry_url)
    evidence = EvidenceStore(redact_all_query=redact_all_query)
    graph = build_presentation_graph(entry_url, context.fetch, evidence)
    raise_when_entry_transport_failed(entry_url, graph, evidence)
    plan = plan_default_samples(graph)
    probe_samples(plan, context.fetch, evidence)
    findings = correlate_findings(
        [
            validate_playlists(graph),
            version_findings(graph),
            delivery_findings(evidence, graph, plan),
            media_findings(graph, context, evidence),
            run_validator_crosscheck(entry_url, context.validator),
            *watch_findings(graph, context, evidence, watch_seconds),
        ]
    )
    profile = classify_presentation(graph)
    return InspectionReport(
        summary=summarize_presentation(profile, findings),
        presentation=build_inventory(graph),
        findings=findings,
        evidence=evidence,
    )


def watch_findings(
    graph: PresentationGraph,
    context: ProbeContext,
    evidence: EvidenceStore,
    watch_seconds: float | None,
) -> list[list[Finding]]:
    if not watch_seconds:
        return []
    window = min(watch_seconds, float(context.settings.hls_max_watch_seconds))
    _, findings = watch_media_playlists(graph, context, evidence, window)
    return findings


def raise_when_entry_transport_failed(
    entry_url: str, graph: PresentationGraph, evidence: EvidenceStore
) -> None:
    node = graph.nodes.get(entry_url)
    if node is None or not node.evidence_ids:
        return
    exchange = evidence.exchanges[node.evidence_ids[0]]
    if exchange.transport_error is not None:
        raise entry_point_unreachable(entry_url, ConnectionError(exchange.transport_error))


def validate_playlists(graph: PresentationGraph) -> list[Finding]:
    findings: list[Finding] = []
    for parsed in graph.playlists.values():
        findings.extend(validate_syntax(parsed.url, parsed.lines))
        if parsed.multivariant is not None:
            findings.extend(validate_multivariant(parsed.url, parsed.multivariant))
            findings.extend(validate_renditions(parsed.url, parsed.multivariant))
        if parsed.media is not None:
            findings.extend(validate_media_playlist(parsed.url, parsed.media))
            findings.extend(validate_encryption(parsed.url, parsed.media))
    return findings


def version_findings(graph: PresentationGraph) -> list[Finding]:
    findings: list[Finding] = []
    for parsed in graph.playlists.values():
        if parsed.multivariant is not None:
            required, reasons = required_multivariant_version(parsed.multivariant)
            findings.extend(
                compute_version_findings(parsed.url, parsed.multivariant.version, required, reasons)
            )
        if parsed.media is not None:
            required, reasons = required_media_version(parsed.media)
            findings.extend(
                compute_version_findings(parsed.url, parsed.media.version, required, reasons)
            )
    return findings


def delivery_findings(
    evidence: EvidenceStore, graph: PresentationGraph, sample_plan: SamplePlan
) -> list[Finding]:
    resource_types: dict[str, str] = {
        redact_url(url, redact_all_query=evidence.redact_all_query): node.node_type
        for url, node in graph.nodes.items()
    }
    for url, resource_type in sample_plan.resource_types.items():
        resource_types.setdefault(
            redact_url(url, redact_all_query=evidence.redact_all_query), resource_type
        )
    gap_urls = {
        redact_url(url, redact_all_query=evidence.redact_all_query) for url in sample_plan.gap_urls
    }
    return derive_unreachable_findings(evidence, resource_types, gap_urls)
