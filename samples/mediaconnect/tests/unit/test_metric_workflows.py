from datetime import UTC, datetime

from mediaconnect_mcp.adapters.cloudwatch.read_flow_metrics import (
    FlowMetrics,
    MetricCategory,
    MetricPoint,
    MetricSeries,
)
from mediaconnect_mcp.workflows.build_metrics_table import build_metrics_table
from mediaconnect_mcp.workflows.identify_flow_issues import (
    IssueSeverity,
    identify_flow_issues,
)
from mediaconnect_mcp.workflows.inspect_all_flow_metrics import AllFlowMetrics

FLOW_ARN = "arn:aws:mediaconnect:us-west-2:111122223333:flow:demo-flow:flow-1"
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def source_health_metrics():
    return FlowMetrics(
        flow_arn=FLOW_ARN,
        category=MetricCategory.SOURCE_HEALTH,
        hours_back=1,
        series=[
            MetricSeries(
                name="SourcePacketLossPercent",
                label="SourcePacketLossPercent",
                status="Complete",
                points=[MetricPoint(at=NOW, value=7.5)],
            ),
            MetricSeries(
                name="SourceConnected",
                label="SourceConnected",
                status="Complete",
                points=[MetricPoint(at=NOW, value=1)],
            ),
        ],
    )


def test_identify_flow_issues_flags_packet_loss_but_not_connected_state():
    result = identify_flow_issues(
        AllFlowMetrics(flow_arn=FLOW_ARN, categories=[source_health_metrics()])
    )

    assert result.issue_count == 1
    assert result.issues[0].metric == "SourcePacketLossPercent"
    assert result.issues[0].severity is IssueSeverity.HIGH


def test_build_metrics_table_returns_chronological_typed_rows():
    result = build_metrics_table(
        AllFlowMetrics(flow_arn=FLOW_ARN, categories=[source_health_metrics()])
    )

    assert result.row_count == 2
    assert {row.metric for row in result.rows} == {
        "SourcePacketLossPercent",
        "SourceConnected",
    }
