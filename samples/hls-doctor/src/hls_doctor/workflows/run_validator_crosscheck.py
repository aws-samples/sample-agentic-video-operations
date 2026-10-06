"""Merge Apple mediastreamvalidator output into findings as an independent check."""

from hls_doctor.adapters.applevalidator.validator_report import ValidateStream
from hls_doctor.domain.correlate.finding_model import Finding, create_finding, observe
from hls_doctor.domain.correlate.severity_model import Confidence, Severity
from media_ops_contracts.tool_failure import ToolFailure

MAX_REPORTED_ISSUES = 10


def run_validator_crosscheck(entry_url: str, validator: ValidateStream | None) -> list[Finding]:
    """The crosscheck degrades gracefully: unavailable means no finding at all."""
    if validator is None:
        return []
    try:
        report = validator(entry_url)
    except ToolFailure:
        return []
    if not report.available:
        return []
    if not report.issues:
        return [
            create_finding(
                "Apple validator reports no conformance errors",
                Severity.INFO,
                Confidence.CONFIRMED,
                "conformance",
                [entry_url],
                [observe("mediastreamvalidator completed with an empty issue list")],
                "An independent conformance pass agrees with this inspection.",
                "None.",
            )  # fmt: skip
        ]
    shown = report.issues[:MAX_REPORTED_ISSUES]
    return [
        create_finding(
            f"Apple validator reports {len(report.issues)} conformance issue(s)",
            Severity.WARNING,
            Confidence.HIGH,
            "conformance",
            [entry_url],
            [observe(f"[{issue.severity}] {issue.message}") for issue in shown],
            "Apple's validator flags authoring issues this inspection should corroborate.",
            "Apple clients enforce these rules most strictly.",
            next_probe="Compare each validator issue with this report's findings.",
        )  # fmt: skip
    ]
