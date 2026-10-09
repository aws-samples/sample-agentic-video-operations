"""Delivery-evidence correlations (spec §18): HTTP patterns become findings."""

from hls_doctor.adapters.http.http_exchange import HttpExchange
from hls_doctor.domain.correlate.finding_model import Finding, create_finding, observe
from hls_doctor.domain.correlate.severity_model import Confidence, Severity
from hls_doctor.domain.evidence.evidence_store import EvidenceStore

RESOURCE_IMPACT = {
    "media_playlist": "The rendition cannot be loaded; players drop or fail over.",
    "multivariant": "The presentation cannot start.",
    "segment": "Players stall or skip when they reach this segment.",
    "init_section": "No segment of the rendition can be decoded.",
    "key": "Encrypted segments cannot be decrypted; playback stops.",
    "steering_manifest": "Pathway selection falls back to defaults.",
    "interstitial_asset_list": "The interstitial cannot play; behavior depends on RESTRICT.",
}


def derive_unreachable_findings(
    evidence: EvidenceStore, resource_types: dict[str, str], gap_urls: set[str]
) -> list[Finding]:
    """One finding per probed URL whose every observation failed.

    `resource_types` maps a redacted URL to its node type; `gap_urls` holds
    segment URLs correctly marked with EXT-X-GAP, which are reported as INFO.
    """
    findings: list[Finding] = []
    by_url: dict[str, list[tuple[str, HttpExchange]]] = {}
    for evidence_id, exchange in evidence.exchanges.items():
        by_url.setdefault(exchange.requested_url, []).append((evidence_id, exchange))
    for url, observed in by_url.items():
        if any(exchange.ok for _, exchange in observed):
            continue
        findings.append(build_unreachable_finding(url, observed, resource_types, gap_urls))
    return findings


def build_unreachable_finding(
    url: str,
    observed: list[tuple[str, HttpExchange]],
    resource_types: dict[str, str],
    gap_urls: set[str],
) -> Finding:
    resource_type = resource_types.get(url, "segment")
    observations = [
        observe(describe_failure(exchange), evidence_id) for evidence_id, exchange in observed
    ]
    if url in gap_urls:
        return create_finding(
            "Unavailable segment is correctly signaled with EXT-X-GAP",
            Severity.INFO, Confidence.CONFIRMED, "delivery", [url], observations,
            "The playlist declares the gap, so clients skip it without error.",
            "None expected; conforming players play through the gap.",
            standards_reference="RFC 8216 EXT-X-GAP",
        )  # fmt: skip
    statuses = {exchange.status for _, exchange in observed if exchange.status}
    return create_finding(
        f"Unreachable {resource_type.replace('_', ' ')}",
        Severity.ERROR, Confidence.CONFIRMED, "delivery", [url], observations,
        f"Every probe of this {resource_type.replace('_', ' ')} failed"
        f" ({', '.join(str(s) for s in sorted(statuses)) or 'transport errors'}).",
        RESOURCE_IMPACT.get(resource_type, "Playback is degraded."),
        likely_causes=["missing object at origin", "packaging error", "access control"],
        next_probe="Request the object directly from the origin, bypassing the CDN.",
    )  # fmt: skip


def describe_failure(exchange: HttpExchange) -> str:
    when = f"at +{exchange.at_ms} ms"
    if exchange.transport_error:
        return f"Request failed with {exchange.transport_error} {when}"
    return f"Returned HTTP {exchange.status} {when}"
