"""Assemble, dedupe and rank findings; assign stable ids (spec §10, §20)."""

from hls_doctor.domain.correlate.finding_model import Finding
from hls_doctor.domain.correlate.severity_model import SEVERITY_ORDER, Severity


def correlate_findings(groups: list[list[Finding]]) -> list[Finding]:
    """Merge finding groups from every analysis stage into one ranked list."""
    merged: list[Finding] = []
    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    for group in groups:
        for finding in group:
            key = (finding.title, finding.category, tuple(finding.affected_resources))
            if key not in seen:
                seen.add(key)
                merged.append(finding)
    merged.sort(key=lambda finding: SEVERITY_ORDER[finding.severity])
    return [
        finding.model_copy(update={"finding_id": f"f{index}"})
        for index, finding in enumerate(merged, start=1)
    ]


def count_by_severity(findings: list[Finding]) -> dict[str, int]:
    counts = {severity.value.lower(): 0 for severity in Severity}
    for finding in findings:
        counts[finding.severity.value.lower()] += 1
    return counts


def overall_status(findings: list[Finding]) -> str:
    counts = count_by_severity(findings)
    if counts["fatal"]:
        return "failed"
    if counts["error"]:
        return "degraded"
    if counts["warning"]:
        return "at-risk"
    return "healthy"
