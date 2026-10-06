"""Describe transport metadata for a MediaConnect flow source."""

from datetime import datetime
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel

from media_ops_contracts.classify_aws_error import classify_aws_error


class FlowSourceMetadata(BaseModel):
    flow_arn: str
    observed_at: datetime | None = None
    transport_media_info: dict[str, Any]
    ndi_info: dict[str, Any] | None = None
    messages: list[dict[str, Any]]


def describe_flow_source_metadata(media_connect: Any, flow_arn: str) -> FlowSourceMetadata:
    """Return the source's transport-stream and NDI metadata."""
    try:
        response = media_connect.describe_flow_source_metadata(FlowArn=flow_arn)
    except (BotoCoreError, ClientError) as error:
        raise classify_aws_error(
            error,
            operation="Describe MediaConnect source metadata",
        ) from error
    return FlowSourceMetadata(
        flow_arn=response.get("FlowArn", flow_arn),
        observed_at=response.get("Timestamp"),
        transport_media_info=response.get("TransportMediaInfo", {}),
        ndi_info=response.get("NdiInfo"),
        messages=response.get("Messages", []),
    )
