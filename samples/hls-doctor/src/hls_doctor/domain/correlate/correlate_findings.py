"""Assemble, roll up and rank findings; assign stable ids (spec §10, §20).

One systemic defect that appears on several resources becomes a single
finding whose affected_resources carries every URL, so a report says
"across 3 renditions" instead of repeating itself three times.
"""

from hls_doctor.domain.correlate.finding_model import Finding
from hls_doctor.domain.correlate.severity_model import SEVERITY_ORDER, Severity

MAX_MERGED_OBSERVATIONS = 12


def correlate_findings(groups: list[list[Finding]]) -> list[Finding]:
    """Merge finding groups from every analysis stage into one ranked list."""
    merged: dict[tuple[str, str], Finding] = {}
    for group in groups:
        for finding in group:
            key = (finding.title, finding.category)
            existing = merged.get(key)
            merged[key] = finding if existing is None else roll_up(existing, finding)
    ranked = sorted(merged.values(), key=lambda finding: SEVERITY_ORDER[finding.severity])
    return [
        finding.model_copy(update={"finding_id": f"f{index}"})
        for index, finding in enumerate(ranked, start=1)
    ]


def roll_up(existing: Finding, addition: Finding) -> Finding:
    """The same defect on another resource: merge resources and evidence."""
    resources = list(existing.affected_resources)
    resources.extend(
        resource for resource in addition.affected_resources if resource not in resources
    )
    observations = list(existing.observations)
    for observation in addition.observations:
        if observation not in observations and len(observations) < MAX_MERGED_OBSERVATIONS:
            observations.append(observation)
    return existing.model_copy(
        update={"affected_resources": resources, "observations": observations}
    )


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
