"""List MediaConnect flows."""

from typing import Any

from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel

from media_ops_contracts.classify_aws_error import classify_aws_error
from mediaconnect_mcp.adapters.media_connect.describe_flow import FlowState, _parse_state


class ListedFlow(BaseModel):
    flow_arn: str
    name: str
    state: FlowState
    description: str | None = None
    source_type: str | None = None


class FlowList(BaseModel):
    flows: list[ListedFlow]
    count: int


def list_flows(media_connect: Any) -> FlowList:
    """Return every flow visible in the configured region."""
    try:
        pages = media_connect.get_paginator("list_flows").paginate()
        flows = [_translate_flow(flow) for page in pages for flow in page.get("Flows", [])]
    except (BotoCoreError, ClientError) as error:
        raise classify_aws_error(error, operation="List MediaConnect flows") from error
    return FlowList(flows=flows, count=len(flows))


def _translate_flow(flow: dict[str, Any]) -> ListedFlow:
    return ListedFlow(
        flow_arn=flow.get("FlowArn", ""),
        name=flow.get("Name", "unnamed"),
        state=_parse_state(flow.get("Status")),
        description=flow.get("Description"),
        source_type=flow.get("SourceType"),
    )
