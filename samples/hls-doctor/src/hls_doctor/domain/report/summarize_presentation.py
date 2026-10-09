"""Build the report summary and inventory blocks from analysis results."""

from hls_doctor.domain.correlate.correlate_findings import count_by_severity, overall_status
from hls_doctor.domain.correlate.finding_model import Finding
from hls_doctor.domain.graph.build_presentation_graph import PresentationGraph
from hls_doctor.domain.graph.classify_presentation import PresentationProfile
from hls_doctor.domain.report.report_model import (
    PresentationInventory,
    ReportSummary,
)


def summarize_presentation(profile: PresentationProfile, findings: list[Finding]) -> ReportSummary:
    counts = count_by_severity(findings)
    return ReportSummary(
        status=overall_status(findings),
        presentation_type=profile.presentation_type,
        hls_version_declared=profile.declared_version,
        features=profile.features,
        fatal=counts["fatal"],
        errors=counts["error"],
        warnings=counts["warning"],
        info=counts["info"],
    )


def build_inventory(graph: PresentationGraph) -> PresentationInventory:
    inventory = PresentationInventory()
    for node in graph.nodes.values():
        if node.role in ("video", "iframe") and node.node_type != "multivariant":
            inventory.variants.append(node)
        elif node.role in ("audio", "subtitles", "closed-captions"):
            inventory.renditions.append(node)
        else:
            inventory.other_resources.append(node)
    return inventory
