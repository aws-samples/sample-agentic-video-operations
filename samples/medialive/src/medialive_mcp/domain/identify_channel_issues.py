"""Score MediaLive health per category and list issues (pure decision, guidelines §8).

The rules and penalties are the ones the previous per-category monitors used; they now
apply to every pipeline instead of pipeline 0 only.
"""

from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel

from medialive_mcp.domain.metric_catalog import CATEGORY_METRICS
from medialive_mcp.domain.metric_series import MetricSeries


class Test(StrEnum):
    TOTAL_ABOVE = "total above"
    AVERAGE_ABOVE = "average above"
    ANY_ABOVE = "any above"
    ANY_BELOW = "any below"


@dataclass(frozen=True)
class Rule:
    category: str
    metric: str
    test: Test
    threshold: float
    penalty: int


RULES = (
    Rule("channel_health", "ActiveAlerts", Test.TOTAL_ABOVE, 0, 30),
    Rule("channel_health", "DroppedFrames", Test.TOTAL_ABOVE, 0, 20),
    Rule("channel_health", "FillMsec", Test.AVERAGE_ABOVE, 100, 15),
    Rule("channel_health", "PipelinesLocked", Test.ANY_BELOW, 1, 10),
    Rule("input_health", "InputLossSeconds", Test.TOTAL_ABOVE, 0, 30),
    Rule("input_health", "RtpPacketsLost", Test.TOTAL_ABOVE, 0, 25),
    Rule("input_health", "ChannelInputErrorSeconds", Test.TOTAL_ABOVE, 0, 20),
    Rule("output_health", "Output4xxErrors", Test.TOTAL_ABOVE, 0, 30),
    Rule("output_health", "Output5xxErrors", Test.TOTAL_ABOVE, 0, 30),
    Rule("output_health", "DroppedFrames", Test.TOTAL_ABOVE, 0, 20),
    Rule("media_health", "ChannelInputErrorSeconds", Test.TOTAL_ABOVE, 0, 25),
    Rule("media_health", "FillMsec", Test.AVERAGE_ABOVE, 100, 20),
    Rule("content_quality", "MqcsBlackFrameDetected", Test.ANY_ABOVE, 0, 25),
    Rule("content_quality", "MqcsFreezeFrameDetected", Test.ANY_ABOVE, 0, 25),
    Rule("content_quality", "MqcsContinuityCounterErrors", Test.TOTAL_ABOVE, 0, 15),
    Rule("content_quality", "InputLossSeconds", Test.TOTAL_ABOVE, 0, 20),
)


class ChannelIssue(BaseModel):
    category: str
    metric: str
    pipeline: str
    severity: str
    description: str


class CategoryHealth(BaseModel):
    score: int
    status: str


class ChannelHealthReport(BaseModel):
    channel_id: str
    overall_score: int
    status: str
    categories: dict[str, CategoryHealth]
    issues: list[ChannelIssue]


def identify_channel_issues(channel_id: str, series: list[MetricSeries]) -> ChannelHealthReport:
    findings = [(rule, found) for rule in RULES for found in _matching_series(rule, series)]
    categories = {}
    for category in CATEGORY_METRICS:
        triggered = {rule for rule, _ in findings if rule.category == category}
        score = max(0, 100 - sum(rule.penalty for rule in triggered))
        categories[category] = CategoryHealth(score=score, status=_status(score))
    issues = [
        ChannelIssue(
            category=rule.category,
            metric=rule.metric,
            pipeline=found.pipeline,
            severity="HIGH" if categories[rule.category].score < 70 else "MEDIUM",
            description=_describe(rule, found.pipeline),
        )
        for rule, found in findings
    ]
    overall = round(sum(health.score for health in categories.values()) / len(categories))
    return ChannelHealthReport(
        channel_id=channel_id,
        overall_score=overall,
        status=_status(overall) if issues else "HEALTHY",
        categories=categories,
        issues=issues,
    )


def _describe(rule: Rule, pipeline: str) -> str:
    return f"{rule.metric} {rule.test} {rule.threshold:g} on pipeline {pipeline}"


def _matching_series(rule: Rule, series: list[MetricSeries]) -> list[MetricSeries]:
    return [s for s in series if s.metric == rule.metric and s.values and _fails(rule, s.values)]


def _fails(rule: Rule, values: list[float]) -> bool:
    if rule.test is Test.TOTAL_ABOVE:
        return sum(values) > rule.threshold
    if rule.test is Test.AVERAGE_ABOVE:
        return sum(values) / len(values) > rule.threshold
    if rule.test is Test.ANY_ABOVE:
        return any(value > rule.threshold for value in values)
    return any(value < rule.threshold for value in values)


def _status(score: int) -> str:
    return "EXCELLENT" if score >= 90 else "GOOD" if score >= 70 else "POOR"
