from datetime import UTC, datetime
from pathlib import Path

from mediaconnect_mcp.adapters.cloudwatch.read_flow_metrics import (
    MetricCategory,
    read_flow_metrics,
)
from mediaconnect_mcp.adapters.media_connect.describe_flow import (
    FlowState,
    describe_flow,
)
from mediaconnect_mcp.workflows.identify_flow_issues import identify_flow_issues
from mediaconnect_mcp.workflows.inspect_all_flow_metrics import AllFlowMetrics

from media_ops_contracts.replay_fixture_client import ReplayFixtureClient

FIXTURES_DIR = Path(__file__).parents[3] / "fixtures"
SCENARIO = "srt_packet_loss"
FLOW_ARN = "arn:aws:mediaconnect:us-west-2:111122223333:flow:demo-contribution:flow-1"
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def test_srt_packet_loss_stays_connected_and_impacts_downstream_input():
    media_connect = ReplayFixtureClient(
        "mediaconnect",
        scenario=SCENARIO,
        fixtures_dir=FIXTURES_DIR,
    )
    cloudwatch = ReplayFixtureClient(
        "cloudwatch",
        scenario=SCENARIO,
        fixtures_dir=FIXTURES_DIR,
    )
    media_live = ReplayFixtureClient(
        "medialive",
        scenario=SCENARIO,
        fixtures_dir=FIXTURES_DIR,
    )

    flow = describe_flow(media_connect, FLOW_ARN)
    metrics = read_flow_metrics(
        cloudwatch,
        FLOW_ARN,
        MetricCategory.SOURCE_HEALTH,
        hours_back=1,
        now=NOW,
    )
    series = {item.name: [point.value for point in item.points] for item in metrics.series}
    issues = identify_flow_issues(AllFlowMetrics(flow_arn=FLOW_ARN, categories=[metrics]))
    downstream = media_live.describe_channel(ChannelId="1234567")
    recorded_metrics = cloudwatch.get_metric_data()
    downstream_loss = next(
        item
        for item in recorded_metrics["MetricDataResults"]
        if item["Id"] == "input_loss_seconds_p0"
    )

    assert flow.state is FlowState.ACTIVE
    assert flow.source["Name"] == "demo-upstream-srt"
    assert series["SourceConnected"] == [1.0, 1.0, 1.0, 1.0]
    assert series["SourcePacketLossPercent"] == sorted(series["SourcePacketLossPercent"])
    assert series["SourcePacketLossPercent"][0] < series["SourcePacketLossPercent"][-1]
    assert series["SourceARQRecovered"] == sorted(series["SourceARQRecovered"])
    assert series["SourceARQRecovered"][0] < series["SourceARQRecovered"][-1]
    assert {issue.metric for issue in issues.issues} >= {
        "SourcePacketLossPercent",
        "SourceNotRecoveredPackets",
    }
    assert downstream["State"] == "RUNNING"
    assert downstream["PipelineDetails"][0]["ActiveInputAttachmentName"] == (
        "demo-mediaconnect-srt"
    )
    assert downstream_loss["Values"] == [0.0, 60.0, 0.0, 120.0]
