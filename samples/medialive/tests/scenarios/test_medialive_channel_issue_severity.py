"""Channel health ratings follow magnitude and the worst finding (backlog T7)."""

import json
from datetime import UTC, datetime, timedelta, timezone

import pytest

from medialive_mcp.adapters.cloudwatch.read_channel_metrics import read_channel_metrics
from medialive_mcp.domain.identify_channel_issues import (
    ChannelContext,
    Status,
    identify_channel_issues,
)
from medialive_mcp.domain.metric_catalog import DEFAULT_STATISTIC, STATISTIC_BY_METRIC
from medialive_mcp.domain.metric_series import MetricSeries

STANDARD_LOCKED = ChannelContext("STANDARD", "PIPELINE_LOCKING")


def series(metric, values, pipeline="0"):
    start = datetime(2026, 10, 5, 11, 0, tzinfo=UTC)
    stamps = [start + timedelta(minutes=5 * i) for i in range(len(values))]
    statistic = STATISTIC_BY_METRIC.get(metric, DEFAULT_STATISTIC)
    return MetricSeries(
        metric=metric, pipeline=pipeline, statistic=statistic, timestamps=stamps, values=values
    )


def severities(report):
    return {(issue.metric, issue.pipeline): issue.severity for issue in report.issues}


def test_ongoing_input_loss_over_half_the_window_is_critical():
    report = identify_channel_issues("1", [series("InputLossSeconds", [0, 300, 300, 300])])
    assert severities(report) == {("InputLossSeconds", "0"): "CRITICAL"}
    assert report.status is Status.CRITICAL


def test_input_loss_over_half_the_window_that_recovered_is_still_high():
    report = identify_channel_issues("1", [series("InputLossSeconds", [300, 300, 300, 0])])
    assert severities(report)[("InputLossSeconds", "0")] == "HIGH"
    assert report.status is Status.DEGRADED


def test_a_short_recovered_glitch_is_only_a_warning():
    report = identify_channel_issues("1", [series("InputLossSeconds", [0, 20, 0, 0])])
    assert severities(report)[("InputLossSeconds", "0")] == "MEDIUM"
    assert report.status is Status.WARNING


def test_an_active_alert_degrades_the_channel():
    report = identify_channel_issues("1", [series("ActiveAlerts", [0, 0, 1])])
    assert severities(report) == {("ActiveAlerts", "0"): "HIGH"}
    assert report.status is Status.DEGRADED


def test_overall_rating_is_the_worst_finding_not_an_average():
    report = identify_channel_issues(
        "1", [series("ActiveAlerts", [1]), series("Output5xxErrors", [3])]
    )
    assert report.status is Status.DEGRADED
    assert report.overall_score == min(
        h.score for h in report.categories.values() if h.score is not None
    )
    assert report.overall_score == 70


def test_a_metric_is_counted_once_even_if_two_categories_show_it():
    report = identify_channel_issues("1", [series("InputLossSeconds", [300]),
                                          series("FillMsec", [500])])  # fmt: skip
    keys = [(issue.metric, issue.pipeline) for issue in report.issues]
    assert sorted(keys) == [("FillMsec", "0"), ("InputLossSeconds", "0")]


@pytest.mark.parametrize(
    ("context", "flagged"),
    [
        (ChannelContext("SINGLE_PIPELINE", None), False),
        (ChannelContext("STANDARD", "EPOCH_LOCKING"), False),
        (STANDARD_LOCKED, True),
    ],
)
def test_pipelines_locked_only_matters_with_pipeline_locking(context, flagged):
    report = identify_channel_issues("1", [series("PipelinesLocked", [0, 0])], context)
    assert (("PipelinesLocked", "0") in severities(report)) is flagged
    assert (report.status is Status.HEALTHY) is not flagged


class LocalOffsetCloudWatch:
    """Answers like boto3 does: timestamps in the host's local offset."""

    def get_metric_data(self, **parameters):
        local = timezone(timedelta(hours=-4))
        stamp = datetime(2026, 10, 5, 8, 0, tzinfo=local)
        return {"MetricDataResults": [
            {"Id": "input_loss_seconds_p0", "Timestamps": [stamp], "Values": [0.0]}
        ]}  # fmt: skip


def test_metric_timestamps_are_reported_in_utc_with_z():
    window = (datetime(2026, 10, 5, 11, 0, tzinfo=UTC), datetime(2026, 10, 5, 13, 0, tzinfo=UTC))
    [loss, _] = read_channel_metrics(LocalOffsetCloudWatch(), "1", ("InputLossSeconds",), window)
    assert loss.timestamps == [datetime(2026, 10, 5, 12, 0, tzinfo=UTC)]
    assert json.loads(loss.model_dump_json())["timestamps"] == ["2026-10-05T12:00:00Z"]
