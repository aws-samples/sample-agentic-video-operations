"""Content Steering manifest validation: structure only, no fetching (spec §16)."""

from typing import Any

from hls_doctor.domain.correlate.finding_model import Finding, create_finding, observe
from hls_doctor.domain.correlate.severity_model import Confidence, Severity
from hls_doctor.domain.playlist.multivariant_model import MultivariantPlaylist


def declared_pathways(playlist: MultivariantPlaylist) -> set[str]:
    pathways = {variant.pathway_id for variant in playlist.variants if variant.pathway_id}
    if playlist.steering is not None and playlist.steering.pathway_id:
        pathways.add(playlist.steering.pathway_id)
    return pathways or {"."}


def validate_steering_manifest(
    url: str, payload: Any, playlist: MultivariantPlaylist
) -> list[Finding]:
    findings: list[Finding] = []
    if not isinstance(payload, dict) or "VERSION" not in payload:
        findings.append(
            create_finding(
                "Steering manifest is not valid steering JSON",
                Severity.ERROR,
                Confidence.CONFIRMED,
                "content-steering",
                [url],
                [observe("The response is not a JSON object with a VERSION field")],
                "The steering manifest must follow the Content Steering format.",
                "Clients ignore steering and stay on the default pathway.",
                standards_reference="Apple Content Steering specification",
            )  # fmt: skip
        )
        return findings
    priority = payload.get("PATHWAY-PRIORITY", [])
    known = declared_pathways(playlist)
    unknown = [pathway for pathway in priority if pathway not in known]
    if unknown:
        findings.append(
            create_finding(
                "Steering manifest references undeclared pathways",
                Severity.WARNING,
                Confidence.CONFIRMED,
                "content-steering",
                [url],
                [
                    observe(
                        f"PATHWAY-PRIORITY lists {unknown} but the multivariant"
                        f" playlist declares {sorted(known)}"
                    )
                ],
                "Every prioritized pathway must exist as variants in the playlist.",
                "Clients cannot move to the missing pathway; steering is partial.",
            )  # fmt: skip
        )
    ttl = payload.get("TTL")
    if not isinstance(ttl, int | float) or ttl <= 0:
        findings.append(
            create_finding(
                "Steering manifest without a usable TTL",
                Severity.WARNING,
                Confidence.CONFIRMED,
                "content-steering",
                [url],
                [observe(f"TTL is {ttl!r}")],
                "The TTL tells clients when to reconsider pathway selection.",
                "Clients never refresh steering, or hammer the steering server.",
            )  # fmt: skip
        )
    return findings
