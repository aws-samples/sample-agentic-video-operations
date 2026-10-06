"""Identify operational issues in typed MediaConnect metrics."""

from enum import StrEnum

from pydantic import BaseModel

from mediaconnect_mcp.workflows.inspect_all_flow_metrics import AllFlowMetrics


class IssueSeverity(StrEnum):
    MEDIUM = "medium"
    HIGH = "high"


class FlowIssue(BaseModel):
    category: str
    metric: str
    severity: IssueSeverity
    peak: float


class FlowIssueReport(BaseModel):
    flow_arn: str
    issues: list[FlowIssue]
    issue_count: int


def identify_flow_issues(metrics: AllFlowMetrics) -> FlowIssueReport:
    """Flag non-zero loss, error, drop, disconnect, and missing-stream metrics."""
    issues = [
        issue
        for category in metrics.categories
        for series in category.series
        if (
            issue := _to_issue(
                category.category.value,
                series.name,
                [point.value for point in series.points],
            )
        )
    ]
    return FlowIssueReport(flow_arn=metrics.flow_arn, issues=issues, issue_count=len(issues))


def _to_issue(category: str, metric: str, values: list[float]) -> FlowIssue | None:
    peak = max(values, default=0)
    issue_terms = (
        "loss",
        "drop",
        "disconnect",
        "error",
        "missing",
        "breaching",
        "notrecovered",
    )
    if peak <= 0 or not any(term in metric.lower() for term in issue_terms):
        return None
    severity = (
        IssueSeverity.HIGH if peak >= 5 or "missing" in metric.lower() else IssueSeverity.MEDIUM
    )
    return FlowIssue(category=category, metric=metric, severity=severity, peak=peak)
