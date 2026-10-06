"""Rate MediaLive channel health and list issues (pure decision, guidelines §8).

- Each metric is judged once, in one category: no issue is counted twice.
- Severity follows magnitude: a failure still present in the latest period is HIGH;
  input loss that is ongoing and covers at least half of the window is CRITICAL.
- The overall status is the worst issue severity, and the overall score is the worst
  category score. Averages hide an outage.
- PipelinesLocked only applies to STANDARD channels that use pipeline locking.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum, StrEnum

from pydantic import BaseModel

from medialive_mcp.domain.metric_catalog import CATEGORY_METRICS
from medialive_mcp.domain.metric_series import MetricSeries

PERIOD_SECONDS = 300


class Severity(IntEnum):
    MEDIUM = 1
    HIGH = 2
    CRITICAL = 3


class Status(StrEnum):
    HEALTHY = "HEALTHY"
    WARNING = "WARNING"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"


STATUS_BY_SEVERITY = {
    Severity.MEDIUM: Status.WARNING,
    Severity.HIGH: Status.DEGRADED,
    Severity.CRITICAL: Status.CRITICAL,
}


@dataclass(frozen=True)
class ChannelContext:
    channel_class: str | None = None
    output_locking_mode: str | None = None

    @property
    def uses_pipeline_locking(self) -> bool:
        return self.channel_class == "STANDARD" and self.output_locking_mode == "PIPELINE_LOCKING"


@dataclass(frozen=True)
class Rule:
    category: str
    metric: str
    fails: Callable[[float], bool]
    threshold_text: str
    penalty: int
    applies: Callable[[ChannelContext], bool] = lambda context: True


RULES = (
    Rule("channel_health", "ActiveAlerts", lambda v: v > 0, "> 0", 30),
    Rule("channel_health", "DroppedFrames", lambda v: v > 0, "> 0", 20),
    Rule("channel_health", "PipelinesLocked", lambda v: v < 1, "< 1", 10,
         applies=lambda context: context.uses_pipeline_locking),
    Rule("input_health", "InputLossSeconds", lambda v: v > 0, "> 0", 30),
    Rule("input_health", "RtpPacketsLost", lambda v: v > 0, "> 0", 25),
    Rule("input_health", "ChannelInputErrorSeconds", lambda v: v > 0, "> 0", 20),
    Rule("output_health", "Output4xxErrors", lambda v: v > 0, "> 0", 30),
    Rule("output_health", "Output5xxErrors", lambda v: v > 0, "> 0", 30),
    Rule("media_health", "FillMsec", lambda v: v > 100, "> 100 ms", 20),
    Rule("content_quality", "MqcsBlackFrameDetected", lambda v: v > 0, "> 0", 25),
    Rule("content_quality", "MqcsFreezeFrameDetected", lambda v: v > 0, "> 0", 25),
    Rule("content_quality", "MqcsContinuityCounterErrors", lambda v: v > 0, "> 0", 15),
)  # fmt: skip


class ChannelIssue(BaseModel):
    category: str
    metric: str
    pipeline: str
    severity: str
    description: str


class CategoryHealth(BaseModel):
    score: int
    status: Status


class ChannelHealthReport(BaseModel):
    channel_id: str
    overall_score: int
    status: Status
    categories: dict[str, CategoryHealth]
    issues: list[ChannelIssue]


def identify_channel_issues(
    channel_id: str, series: list[MetricSeries], context: ChannelContext | None = None
) -> ChannelHealthReport:
    context = context or ChannelContext()
    found = [
        (rule, measured, rate_severity(rule, measured))
        for rule in RULES
        if rule.applies(context)
        for measured in series
        if measured.metric == rule.metric and any(rule.fails(v) for v in measured.values)
    ]
    issues = [
        ChannelIssue(
            category=rule.category,
            metric=rule.metric,
            pipeline=measured.pipeline,
            severity=severity.name,
            description=describe_issue(rule, measured),
        )
        for rule, measured, severity in sorted(found, key=lambda item: -item[2])
    ]
    categories = {category: rate_category(category, found) for category in CATEGORY_METRICS}
    worst = max((severity for _, _, severity in found), default=None)
    return ChannelHealthReport(
        channel_id=channel_id,
        overall_score=min(health.score for health in categories.values()),
        status=STATUS_BY_SEVERITY[worst] if worst else Status.HEALTHY,
        categories=categories,
        issues=issues,
    )


def rate_severity(rule: Rule, measured: MetricSeries) -> Severity:
    ongoing = rule.fails(measured.values[-1])
    if rule.metric == "InputLossSeconds" and ongoing and loss_ratio(measured) >= 0.5:
        return Severity.CRITICAL
    if ongoing or (rule.metric == "InputLossSeconds" and loss_ratio(measured) >= 0.5):
        return Severity.HIGH
    return Severity.MEDIUM


def loss_ratio(measured: MetricSeries) -> float:
    """Share of the window with input loss; values are seconds lost per period."""
    window = len(measured.values) * PERIOD_SECONDS
    return min(1.0, sum(measured.values) / window) if window else 0.0


def rate_category(category: str, found: list) -> CategoryHealth:
    in_category = [(rule, severity) for rule, _, severity in found if rule.category == category]
    penalties = sum({rule.metric: rule.penalty for rule, _ in in_category}.values())
    worst = max((severity for _, severity in in_category), default=None)
    return CategoryHealth(
        score=max(0, 100 - penalties),
        status=STATUS_BY_SEVERITY[worst] if worst else Status.HEALTHY,
    )


def describe_issue(rule: Rule, measured: MetricSeries) -> str:
    where = f"on pipeline {measured.pipeline}"
    now = "still failing in the latest period" if rule.fails(measured.values[-1]) else "recovered"
    if rule.metric == "InputLossSeconds":
        lost = sum(measured.values)
        return f"{lost:g} s of input lost ({loss_ratio(measured):.0%} of the window) {where}, {now}"
    return f"{rule.metric} {rule.threshold_text} {where}, {now}"
