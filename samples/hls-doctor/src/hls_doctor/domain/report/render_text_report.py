"""Human report: diagnosis first, then evidence (spec §23)."""

from hls_doctor.domain.correlate.finding_model import Finding
from hls_doctor.domain.correlate.severity_model import Severity
from hls_doctor.domain.report.report_model import InspectionReport


def render_text_report(report: InspectionReport) -> str:
    lines = ["HLS Doctor", "==========", f"Status: {report.summary.status.upper()}", ""]
    lines.extend(render_overview(report))
    critical = [f for f in report.findings if f.severity in (Severity.FATAL, Severity.ERROR)]
    if critical:
        lines.extend(render_critical(critical[0]))
    lines.extend(render_other_findings(report.findings, skip=critical[:1]))
    if critical and critical[0].next_probe:
        lines.extend(["Next probe", "----------", critical[0].next_probe, ""])
    return "\n".join(lines).rstrip() + "\n"


def render_overview(report: InspectionReport) -> list[str]:
    summary = report.summary
    counts = (
        f"{len(report.presentation.variants)} variant playlist(s),"
        f" {len(report.presentation.renditions)} alternate rendition(s)"
    )
    version = (
        f"HLS version: {summary.hls_version_declared}"
        if summary.hls_version_declared
        else "HLS version: not declared"
    )
    lines = [f"{summary.presentation_type.upper()} HLS, {counts}", version]
    if summary.features:
        lines.append(f"Features: {', '.join(summary.features)}")
    lines.append("")
    return lines


def render_critical(finding: Finding) -> list[str]:
    lines = ["Critical finding", "----------------", finding.title, "", finding.interpretation, ""]
    if finding.observations:
        lines.extend(["Evidence", "--------"])
        lines.extend(observation.statement for observation in finding.observations)
        lines.append("")
    lines.extend(["Playback impact", "---------------", finding.playback_impact, ""])
    return lines


def render_other_findings(findings: list[Finding], skip: list[Finding]) -> list[str]:
    remaining = [finding for finding in findings if finding not in skip]
    if not remaining:
        return []
    lines = ["Other findings", "--------------"]
    lines.extend(f"{finding.severity.value:<8} {finding.title}" for finding in remaining)
    lines.append("")
    return lines
