"""Region-wide metrics are context, never part of a channel's score (T64).

DroppedFrames and SvqTime are published per pipeline and Region only ("Supported dimensions
sets: Pipeline, Region" in the MediaLive user guide, Output metrics): every channel in the
Region combined. Scoring them against one channel blamed it for other channels' frames.
"""

from medialive_mcp.domain.identify_channel_issues import RULES, Status, identify_channel_issues
from medialive_mcp.domain.metric_catalog import REGION_WIDE_METRICS
from medialive_mcp.domain.metric_series import MetricSeries

REGION = {"Region": "us-west-2"}


def dropped(values):
    return MetricSeries(
        metric="DroppedFrames", pipeline="0", statistic="Sum", values=values, dimensions=REGION
    )


def alerts(values):
    return MetricSeries(metric="ActiveAlerts", pipeline="0", statistic="Maximum", values=values)


def test_the_region_wide_metrics_are_the_ones_without_a_channel_dimension():
    assert {"DroppedFrames", "SvqTime"} == REGION_WIDE_METRICS
    assert not [rule for rule in RULES if rule.metric in REGION_WIDE_METRICS]


def test_dropped_frames_in_the_region_never_lower_the_channel_score():
    report = identify_channel_issues("1", [alerts([0, 0]), dropped([0, 30])])

    assert report.issues == []
    assert report.status is Status.HEALTHY
    assert report.overall_score == 100
    assert report.categories["channel_health"].score == 100


def test_region_wide_readings_are_reported_as_context(tmp_path):
    svq = MetricSeries(
        metric="SvqTime", pipeline="1", statistic="Maximum", values=[0, 12.5], dimensions=REGION
    )

    report = identify_channel_issues("1", [alerts([0]), dropped([0, 30]), svq])

    [frames, quality] = report.region_wide
    assert (frames.metric, frames.pipeline, frames.region, frames.worst) == (
        "DroppedFrames", "0", "us-west-2", 30
    )  # fmt: skip
    assert "all channels in us-west-2 combined" in frames.description
    assert "not scored" in frames.description
    assert (quality.metric, quality.worst) == ("SvqTime", 12.5)


def test_region_wide_data_alone_does_not_make_a_category_healthy():
    report = identify_channel_issues("1", [dropped([0, 0])])

    assert report.categories["channel_health"].status is Status.NOT_EMITTED
    assert report.status is Status.NOT_EMITTED
    assert report.overall_score is None


def test_a_rule_added_for_a_region_wide_metric_still_cannot_score_it(monkeypatch):
    import medialive_mcp.domain.identify_channel_issues as issues

    scoring = issues.Rule("channel_health", "DroppedFrames", lambda v: v > 0, "> 0", 20)
    monkeypatch.setattr(issues, "RULES", (*issues.RULES, scoring))

    report = issues.identify_channel_issues("1", [alerts([0]), dropped([0, 30])])

    assert report.issues == [] and report.overall_score == 100
