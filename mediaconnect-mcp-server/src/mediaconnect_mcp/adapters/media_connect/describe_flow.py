"""Describe one MediaConnect flow."""

from enum import StrEnum
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel

from media_ops_contracts.classify_aws_error import classify_aws_error


class FlowState(StrEnum):
    STANDBY = "STANDBY"
    ACTIVE = "ACTIVE"
    UPDATING = "UPDATING"
    DELETING = "DELETING"
    STARTING = "STARTING"
    STOPPING = "STOPPING"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"


class FlowDetails(BaseModel):
    flow_arn: str
    name: str
    state: FlowState
    description: str | None = None
    source: dict[str, Any] | None = None
    outputs: list[dict[str, Any]]
    errors: list[str]


def describe_flow(media_connect: Any, flow_arn: str) -> FlowDetails:
    """Return the current state and topology of one flow."""
    try:
        response = media_connect.describe_flow(FlowArn=flow_arn)
    except (BotoCoreError, ClientError) as error:
        raise classify_aws_error(error, operation="Describe MediaConnect flow") from error
    flow = response.get("Flow", {})
    messages = response.get("Messages", {})
    return FlowDetails(
        flow_arn=flow.get("FlowArn", flow_arn),
        name=flow.get("Name", "unnamed"),
        state=_parse_state(flow.get("Status")),
        description=flow.get("Description"),
        source=flow.get("Source"),
        outputs=flow.get("Outputs", []),
        errors=messages.get("Errors", []),
    )


def _parse_state(value: Any) -> FlowState:
    try:
        return FlowState(value)
    except ValueError:
        return FlowState.UNKNOWN
