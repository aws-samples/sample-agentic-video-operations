from hls_doctor.domain.correlate.correlate_findings import correlate_findings
from hls_doctor.domain.correlate.finding_model import create_finding, observe
from hls_doctor.domain.correlate.severity_model import Confidence, Severity
from hls_doctor.domain.report.render_text_report import render_text_report
from hls_doctor.domain.report.report_model import (
    InspectionReport,
    PresentationInventory,
    ReportSummary,
)
from hls_doctor.entrypoints.parse_cli_arguments import parse_inspect_options
from hls_doctor.entrypoints.run_cli import exit_code


def finding(title: str, severity: Severity):
    return create_finding(
        title, severity, Confidence.HIGH, "delivery", ["https://demo.example/x"],
        [observe("Returned HTTP 404 at +82 ms")],
        "Interpretation.", "Impact.", next_probe="Probe the origin directly.",
    )  # fmt: skip


def test_correlate_assigns_ids_dedupes_and_ranks() -> None:
    error = finding("B", Severity.ERROR)
    findings = correlate_findings(
        [[finding("A", Severity.INFO)], [error, error], [finding("C", Severity.FATAL)]]
    )
    assert [item.title for item in findings] == ["C", "B", "A"]
    assert [item.finding_id for item in findings] == ["f1", "f2", "f3"]


def test_text_report_leads_with_the_critical_finding() -> None:
    findings = correlate_findings([[finding("Unreachable key", Severity.ERROR)]])
    report = InspectionReport(
        summary=ReportSummary(status="degraded", presentation_type="vod", errors=1),
        presentation=PresentationInventory(),
        findings=findings,
    )
    text = render_text_report(report)
    assert text.splitlines()[2] == "Status: DEGRADED"
    assert "Critical finding" in text and "Unreachable key" in text
    assert "Returned HTTP 404 at +82 ms" in text
    assert "Next probe" in text


def test_cli_options_parse_headers_and_flags() -> None:
    options = parse_inspect_options(
        ["inspect", "https://demo.example/m.m3u8", "--header", "X-A: 1",
         "--output", "json", "--watch", "15"]
    )  # fmt: skip
    assert options.headers == {"X-A": "1"}
    assert options.output == "json" and options.watch_seconds == 15


def test_exit_codes_reflect_worst_severity() -> None:
    def report_with(**counts: int) -> InspectionReport:
        return InspectionReport(
            summary=ReportSummary(status="x", presentation_type="vod", **counts),
            presentation=PresentationInventory(),
        )

    assert exit_code(report_with()) == 0
    assert exit_code(report_with(warnings=1)) == 1
    assert exit_code(report_with(errors=1, warnings=2)) == 2
    assert exit_code(report_with(fatal=1, errors=1)) == 3
