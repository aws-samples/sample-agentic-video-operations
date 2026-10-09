"""Metrics are queried with the dimensions and statistic MediaLive publishes (GH25-A7)."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from medialive_mcp.adapters.cloudwatch.read_channel_metrics import (
    MetricScope,
    read_channel_metrics,
)
from medialive_mcp.domain.identify_channel_issues import identify_channel_issues
from medialive_mcp.domain.metric_catalog import ALL_METRICS, CATEGORY_METRICS
from medialive_mcp.domain.metric_series import MetricSeries
from medialive_mcp.workflows.check_channel_health import build_metrics_table, check_channel_issues

START = datetime(2026, 10, 5, 11, 0, tzinfo=UTC)
WINDOW = (START, START + timedelta(hours=1))
ADDITIONAL_MQCS_PORTIONS = (
    "MqcsFillFrameInsertion",
    "MqcsSvq",
    "MqcsVideoFrameDrops",
)


class RecordingCloudWatch:
    """Answers every query with the same values and keeps the queries it was sent."""

    def __init__(self, values=(0.0,)):
        self.values = list(values)
        self.queries = []

    def get_metric_data(self, MetricDataQueries, **_):
        self.queries.extend(MetricDataQueries)
        stamps = [START + timedelta(minutes=5 * i) for i in range(len(self.values))]
        results = [
            {"Id": q["Id"], "Timestamps": stamps, "Values": self.values} for q in MetricDataQueries
        ]
        return {"MetricDataResults": results}


class FakeMediaLive:
    def describe_channel(self, ChannelId):
        groups = [{"Name": "cmaf-ingest"}, {"Name": "hls-backup"}]
        return {"Id": ChannelId, "State": "RUNNING", "EncoderSettings": {"OutputGroups": groups}}


def dimensions(query):
    return {d["Name"]: d["Value"] for d in query["MetricStat"]["Metric"]["Dimensions"]}


def queries_for(cloudwatch, metric):
    return [q for q in cloudwatch.queries if q["MetricStat"]["Metric"]["MetricName"] == metric]


def test_min_mqcs_is_queried_per_output_group_with_the_minimum_statistic():
    cloudwatch = RecordingCloudWatch()

    series = read_channel_metrics(
        cloudwatch, "1", ("MinMQCS",), WINDOW, MetricScope(output_groups=("cmaf-ingest", "hls"))
    )

    queries = queries_for(cloudwatch, "MinMQCS")
    assert {(dimensions(q)["Pipeline"], dimensions(q)["OutputGroupName"]) for q in queries} == {
        ("0", "cmaf-ingest"), ("0", "hls"), ("1", "cmaf-ingest"), ("1", "hls"),
    }  # fmt: skip
    assert {q["MetricStat"]["Stat"] for q in queries} == {"Minimum"}
    assert {(s.pipeline, s.dimensions["OutputGroupName"]) for s in series} == {
        ("0", "cmaf-ingest"), ("0", "hls"), ("1", "cmaf-ingest"), ("1", "hls"),
    }  # fmt: skip


def test_output_group_metrics_are_skipped_without_output_groups():
    cloudwatch = RecordingCloudWatch()

    series = read_channel_metrics(cloudwatch, "1", ("MinMQCS", "Output4xxErrors"), WINDOW)

    assert series == []
    assert cloudwatch.queries == []


def test_channel_metrics_keep_channel_and_pipeline_dimensions_only():
    cloudwatch = RecordingCloudWatch()

    read_channel_metrics(
        cloudwatch,
        "1",
        ("InputLossSeconds", "NetworkIn"),
        WINDOW,
        MetricScope(output_groups=("hls",)),
    )

    loss, network = (
        queries_for(cloudwatch, "InputLossSeconds"),
        queries_for(cloudwatch, "NetworkIn"),
    )
    assert all(set(dimensions(q)) == {"ChannelId", "Pipeline"} for q in loss + network)
    assert {q["MetricStat"]["Stat"] for q in loss} == {"Sum"}
    assert {q["MetricStat"]["Stat"] for q in network} == {"Average"}


def test_the_issue_check_reads_output_groups_from_the_channel():
    cloudwatch = RecordingCloudWatch()
    clients = SimpleNamespace(medialive=FakeMediaLive(), cloudwatch=cloudwatch, region="us-west-2")

    check_channel_issues(clients, "1", hours_back=1)

    queries = queries_for(cloudwatch, "Output5xxErrors")
    groups = {dimensions(q).get("OutputGroupName") for q in queries}
    assert groups == {"cmaf-ingest", "hls-backup"}


def test_input_loss_total_adds_sum_periods_and_averages_have_no_total():
    loss = MetricSeries(
        metric="InputLossSeconds", pipeline="0", statistic="Sum", values=[0, 120, 60]
    )
    network = MetricSeries(metric="NetworkIn", pipeline="0", values=[4.0, 6.0])

    report = identify_channel_issues("1", [loss])

    assert loss.total == 180
    assert network.total is None
    assert report.issues[0].description.startswith("180 s of input lost (20% of the window)")


def test_a_full_mqcs_score_is_healthy_and_a_lower_one_is_an_issue():
    healthy = MetricSeries(
        metric="MqcsFreezeFrameDetected", pipeline="0", statistic="Minimum", values=[100, 100]
    )
    frozen = healthy.model_copy(update={"pipeline": "1", "values": [100, 40]})

    report = identify_channel_issues("1", [healthy, frozen])

    assert [(issue.metric, issue.pipeline) for issue in report.issues] == [
        ("MqcsFreezeFrameDetected", "1")
    ]
    assert "below 100 (worst 40)" in report.issues[0].description


@pytest.mark.parametrize("metric", ADDITIONAL_MQCS_PORTIONS)
def test_each_additional_mqcs_portion_uses_channel_pipeline_and_minimum(metric):
    cloudwatch = RecordingCloudWatch()

    series = read_channel_metrics(cloudwatch, "1", (metric,), WINDOW)

    queries = queries_for(cloudwatch, metric)
    assert [dimensions(query) for query in queries] == [
        {"ChannelId": "1", "Pipeline": "0"},
        {"ChannelId": "1", "Pipeline": "1"},
    ]
    assert {query["MetricStat"]["Stat"] for query in queries} == {"Minimum"}
    assert {measured.metric for measured in series} == {metric}


def test_channel_health_collects_every_additional_mqcs_portion():
    assert set(ADDITIONAL_MQCS_PORTIONS) <= set(CATEGORY_METRICS["content_quality"])
    assert set(ADDITIONAL_MQCS_PORTIONS) <= set(ALL_METRICS)


def test_pipelines_locked_uses_the_minimum_statistic():
    cloudwatch = RecordingCloudWatch()

    read_channel_metrics(cloudwatch, "1", ("PipelinesLocked",), WINDOW)

    assert {q["MetricStat"]["Stat"] for q in queries_for(cloudwatch, "PipelinesLocked")} == {
        "Minimum"
    }


def test_dropped_frames_and_svq_time_are_queried_per_pipeline_and_region():
    cloudwatch = RecordingCloudWatch()

    series = read_channel_metrics(
        cloudwatch, "1", ("DroppedFrames", "SvqTime"), WINDOW, MetricScope(region="us-west-2")
    )

    for metric in ("DroppedFrames", "SvqTime"):
        queries = queries_for(cloudwatch, metric)
        assert [dimensions(q) for q in queries] == [
            {"Pipeline": "0", "Region": "us-west-2"},
            {"Pipeline": "1", "Region": "us-west-2"},
        ]
    assert {s.dimensions["Region"] for s in series} == {"us-west-2"}


def test_audio_levels_are_queried_per_audio_description():
    cloudwatch = RecordingCloudWatch()
    scope = MetricScope(audio_descriptions=("audio_1", "audio_2"))

    read_channel_metrics(cloudwatch, "1", ("OutputAudioLevelLkfs",), WINDOW, scope)

    names = {
        dimensions(q)["AudioDescriptionName"]
        for q in queries_for(cloudwatch, "OutputAudioLevelLkfs")
    }  # noqa: E501
    assert names == {"audio_1", "audio_2"}


def test_a_region_wide_reading_says_it_is_not_specific_to_the_channel():
    dropped = MetricSeries(
        metric="DroppedFrames", pipeline="0", statistic="Sum", values=[0, 3],
        dimensions={"Region": "us-west-2"},
    )  # fmt: skip

    report = identify_channel_issues("1", [dropped])

    assert report.issues == []  # context only: never a channel issue
    [reading] = report.region_wide
    assert "all channels in us-west-2 combined" in reading.description
    assert reading.region == "us-west-2"


def test_metrics_without_datapoints_are_not_emitted_never_healthy():
    loss = MetricSeries(metric="InputLossSeconds", pipeline="0", statistic="Sum")
    network = MetricSeries(metric="NetworkIn", pipeline="0", values=[5.0])
    alerts = MetricSeries(metric="ActiveAlerts", pipeline="0", statistic="Maximum", values=[0])

    report = identify_channel_issues("1", [loss, network, alerts])

    assert report.not_emitted == ["InputLossSeconds"]
    # NetworkIn has datapoints but no rule: input health is still unknown, not healthy.
    assert report.categories["input_health"].status == "NOT_EMITTED"
    assert report.categories["input_health"].score is None
    assert report.categories["channel_health"].status == "HEALTHY"


def test_a_channel_with_no_datapoints_at_all_is_not_emitted():
    report = identify_channel_issues("1", [MetricSeries(metric="NetworkIn", pipeline="0")])

    assert report.status == "NOT_EMITTED"
    assert report.overall_score is None


def test_the_metrics_table_carries_each_series_dimensions():
    cloudwatch = RecordingCloudWatch(values=(1.0, 2.0))
    clients = SimpleNamespace(medialive=FakeMediaLive(), cloudwatch=cloudwatch, region="us-west-2")

    rows = build_metrics_table(clients, "1", hours_back=1)

    groups = {
        row.dimensions.get("OutputGroupName") for row in rows if row.metric == "Output4xxErrors"
    }  # noqa: E501
    assert groups == {"cmaf-ingest", "hls-backup"}
    assert all(row.dimensions == {} for row in rows if row.metric == "NetworkIn")


def test_audio_levels_use_the_minimum_statistic():
    cloudwatch = RecordingCloudWatch()
    scope = MetricScope(audio_descriptions=("audio_1",))

    read_channel_metrics(
        cloudwatch, "1", ("OutputAudioLevelDbfs", "OutputAudioLevelLkfs"), WINDOW, scope
    )  # noqa: E501

    assert {q["MetricStat"]["Stat"] for q in cloudwatch.queries} == {"Minimum"}
