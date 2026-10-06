"""Read whether a flow's source monitoring produces thumbnails and content-quality metrics."""

from typing import Any

from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel

from media_ops_contracts.classify_aws_error import classify_aws_error


class SourceMonitoring(BaseModel):
    flow_arn: str
    flow_state: str | None
    source_name: str | None  # the flow's (primary) source
    source_names: list[str]  # every source, for a failover flow
    thumbnails: bool | None  # SourceMonitoringConfig.ThumbnailState; None = not reported
    content_quality: bool | None  # ContentQualityAnalysisState: Black/Frozen frame metrics


def read_source_monitoring(media_connect: Any, flow_arn: str) -> SourceMonitoring:
    try:
        response = media_connect.describe_flow(FlowArn=flow_arn)
    except (BotoCoreError, ClientError) as error:
        raise classify_aws_error(error, operation="Describe MediaConnect flow") from error
    flow = response.get("Flow", {})
    config = flow.get("SourceMonitoringConfig") or {}
    sources = flow.get("Sources") or ([flow["Source"]] if flow.get("Source") else [])
    return SourceMonitoring(
        flow_arn=flow.get("FlowArn", flow_arn),
        flow_state=flow.get("Status"),
        source_name=(flow.get("Source") or {}).get("Name"),
        source_names=[source.get("Name", "unnamed") for source in sources],
        thumbnails=state(config.get("ThumbnailState")),
        content_quality=state(config.get("ContentQualityAnalysisState")),
    )


def state(value: Any) -> bool | None:
    return {"ENABLED": True, "DISABLED": False}.get(value)
