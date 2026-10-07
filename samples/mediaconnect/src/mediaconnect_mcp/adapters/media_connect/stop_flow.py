"""Stop one operator-approved MediaConnect flow."""

from datetime import datetime
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from media_ops_contracts.approved_action import ApprovedAction
from media_ops_contracts.classify_aws_error import classify_aws_error
from media_ops_contracts.require_action_approval import require_action_approval
from mediaconnect_mcp.adapters.media_connect.describe_flow import FlowState, describe_flow
from mediaconnect_mcp.adapters.media_connect.verify_flow_state import (
    DEFAULT_FLOW_POLLER,
    FlowActionResult,
    FlowPoller,
    verify_flow_state,
)


def stop_flow(
    approved_action: ApprovedAction | None,
    media_connect: Any,
    signing_key: bytes,
    now: datetime,
    poller: FlowPoller = DEFAULT_FLOW_POLLER,
) -> FlowActionResult:
    """Idempotent: a flow already STANDBY is a verified no-op, and MediaConnect isn't called."""
    flow_arn = approved_action.resource_id if approved_action else ""
    require_action_approval(
        approved_action,
        action="stop_flow",
        signing_key=signing_key,
        now=now,
        resource_id=flow_arn,
    )
    before = describe_flow(media_connect, flow_arn)
    if before.state is not FlowState.STANDBY:
        try:
            media_connect.stop_flow(FlowArn=flow_arn)
        except (BotoCoreError, ClientError) as error:
            raise classify_aws_error(error, operation="Stop MediaConnect flow") from error
    after = verify_flow_state(media_connect, flow_arn, FlowState.STANDBY, poller)
    return FlowActionResult(
        action="stop_flow",
        resource_id=flow_arn,
        before=before,
        after=after,
        verified=after.state is FlowState.STANDBY,
    )
