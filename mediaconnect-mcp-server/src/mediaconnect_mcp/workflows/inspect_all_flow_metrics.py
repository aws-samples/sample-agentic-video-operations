"""Read every MediaConnect metric category."""

from collections.abc import Callable

from pydantic import BaseModel

from mediaconnect_mcp.adapters.cloudwatch.read_flow_metrics import (
    FlowMetrics,
    MetricCategory,
)


class AllFlowMetrics(BaseModel):
    flow_arn: str
    categories: list[FlowMetrics]


def inspect_all_flow_metrics(
    flow_arn: str,
    read_metrics: Callable[[MetricCategory], FlowMetrics],
) -> AllFlowMetrics:
    """Return all five metric categories through one injected read boundary."""
    return AllFlowMetrics(
        flow_arn=flow_arn,
        categories=[read_metrics(category) for category in MetricCategory],
    )
