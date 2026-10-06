"""Flatten typed MediaConnect metrics for charting."""

from datetime import datetime

from pydantic import BaseModel

from mediaconnect_mcp.workflows.inspect_all_flow_metrics import AllFlowMetrics


class MetricTableRow(BaseModel):
    at: datetime
    category: str
    metric: str
    value: float


class MetricsTable(BaseModel):
    flow_arn: str
    rows: list[MetricTableRow]
    row_count: int


def build_metrics_table(metrics: AllFlowMetrics) -> MetricsTable:
    """Return all points in chronological tabular form."""
    rows = [
        MetricTableRow(
            at=point.at,
            category=category.category.value,
            metric=series.name,
            value=point.value,
        )
        for category in metrics.categories
        for series in category.series
        for point in series.points
    ]
    rows.sort(key=lambda row: row.at)
    return MetricsTable(flow_arn=metrics.flow_arn, rows=rows, row_count=len(rows))
