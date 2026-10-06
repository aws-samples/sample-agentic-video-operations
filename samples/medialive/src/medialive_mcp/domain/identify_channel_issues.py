"""Rate MediaLive channel health and list issues (pure decision, guidelines §8).

- Each metric is judged once, in one category: no issue is counted twice.
- Severity follows magnitude: a failure still present in the latest period is HIGH;
  input loss that is ongoing and covers at least half of the window is CRITICAL.
- The overall status is the worst issue severity, and the overall score is the worst
  category score. Averages hide an outage.
- PipelinesLocked only applies to STANDARD channels that use pipeline locking.
- Values carry the metric's recommended statistic: InputLossSeconds is a Sum, so its periods
  add up to seconds lost. MQCS portions are scores where 100 means no problem.
- A metric with no datapoints is not emitted, which is unknown, never healthy. A category
  none of whose rated metrics emitted is NOT_EMITTED and has no score.
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
    NOT_EMITTED = "NOT_EMITTED"


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
    Rule("content_quality", "MqcsBlackFrameDetected", lambda v: v < 100, "below 100", 25),
    Rule("content_quality", "MqcsFreezeFrameDetected", lambda v: v < 100, "below 100", 25),
    Rule("content_quality", "MqcsContinuityCounterErrors", lambda v: v < 100, "below 100", 15),
)  # fmt: skip


class ChannelIssue(BaseModel):
    category: str
    metric: str
    pipeline: str
    dimensions: dict[str, str] = {}
    severity: str
    description: str


class CategoryHealth(BaseModel):
    score: int | None  # None when no metric of the category emitted
    status: Status


class ChannelHealthReport(BaseModel):
    channel_id: str
    overall_score: int | None
    status: Status
    categories: dict[str, CategoryHealth]
    issues: list[ChannelIssue]
    not_emitted: list[str]  # metrics queried that returned no datapoints at all


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
            dimensions=measured.dimensions,
            severity=severity.name,
            description=describe_issue(rule, measured),
        )
        for rule, measured, severity in sorted(found, key=lambda item: -item[2])
    ]
    emitted = {measured.metric for measured in series if measured.emitted}
    categories = {
        category: rate_category(category, found, emitted) for category in CATEGORY_METRICS
    }
    scores = [health.score for health in categories.values() if health.score is not None]
    worst = max((severity for _, _, severity in found), default=None)
    if worst:
        status = STATUS_BY_SEVERITY[worst]
    else:
        status = Status.HEALTHY if scores else Status.NOT_EMITTED
    return ChannelHealthReport(
        channel_id=channel_id,
        overall_score=min(scores, default=None),
        status=status,
        categories=categories,
        issues=issues,
        not_emitted=sorted({measured.metric for measured in series} - emitted),
    )


def rate_severity(rule: Rule, measured: MetricSeries) -> Severity:
    ongoing = rule.fails(measured.values[-1])
    if rule.metric == "InputLossSeconds" and ongoing and loss_ratio(measured) >= 0.5:
        return Severity.CRITICAL
    if ongoing or (rule.metric == "InputLossSeconds" and loss_ratio(measured) >= 0.5):
        return Severity.HIGH
    return Severity.MEDIUM


def loss_ratio(measured: MetricSeries) -> float:
    """Share of the window with input loss, from the Sum series of seconds lost per period."""
    window = len(measured.values) * PERIOD_SECONDS
    return min(1.0, (measured.total or 0.0) / window) if window else 0.0


def rate_category(category: str, found: list, emitted: set[str]) -> CategoryHealth:
    """NOT_EMITTED unless a metric this category rates has datapoints."""
    rated = {rule.metric for rule in RULES if rule.category == category}
    if not emitted.intersection(rated):
        return CategoryHealth(score=None, status=Status.NOT_EMITTED)
    in_category = [(rule, severity) for rule, _, severity in found if rule.category == category]
    penalties = sum({rule.metric: rule.penalty for rule, _ in in_category}.values())
    worst = max((severity for _, severity in in_category), default=None)
    return CategoryHealth(
        score=max(0, 100 - penalties),
        status=STATUS_BY_SEVERITY[worst] if worst else Status.HEALTHY,
    )


def describe_issue(rule: Rule, measured: MetricSeries) -> str:
    where = f"on pipeline {measured.pipeline}"
    labels = {"OutputGroupName": "output group", "AudioDescriptionName": "audio"}
    for name, value in measured.dimensions.items():
        if name == "Region":
            where += f" (region-wide metric: all channels in {value} combined, not only this one)"
        else:
            where += f", {labels.get(name, name)} {value}"
    now = "still failing in the latest period" if rule.fails(measured.values[-1]) else "recovered"
    if rule.metric == "InputLossSeconds" and measured.total is not None:
        share = f"{loss_ratio(measured):.0%} of the window"
        return f"{measured.total:g} s of input lost ({share}) {where}, {now}"
    worst = min(measured.values) if rule.threshold_text == "below 100" else max(measured.values)
    return f"{rule.metric} {rule.threshold_text} (worst {worst:g}) {where}, {now}"
