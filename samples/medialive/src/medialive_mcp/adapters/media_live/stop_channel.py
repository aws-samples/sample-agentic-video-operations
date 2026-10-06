"""Stop one approved MediaLive channel and verify it reaches IDLE."""

from typing import Any

from media_ops_contracts.action_result import ActionResult
from media_ops_contracts.approved_action import ApprovedAction
from media_ops_contracts.call_aws_operation import call_aws_operation
from media_ops_contracts.require_action_approval import require_action_approval
from medialive_mcp.adapters.media_live.describe_channel import describe_channel
from medialive_mcp.adapters.media_live.media_live_records import ChannelState
from medialive_mcp.domain.write_requirements import (
    ApprovalCheck,
    VerificationPolicy,
    wait_for_condition,
)

ACTION = "stop_channel"
TARGET_STATE = ChannelState.IDLE


def stop_channel(
    medialive: Any,
    approved_action: ApprovedAction,
    check: ApprovalCheck,
    policy: VerificationPolicy,
) -> ActionResult:
    """Idempotent in MediaLive: a channel already IDLE needs no idempotency key."""
    require_action_approval(
        approved_action, action=ACTION, signing_key=check.signing_key, now=check.now
    )
    channel_id = approved_action.resource_id
    before = describe_channel(medialive, channel_id).state
    call_aws_operation(medialive, ACTION, ChannelId=channel_id)
    after = wait_for_condition(
        lambda: describe_channel(medialive, channel_id).state,
        lambda state: state is TARGET_STATE,
        policy,
    )
    return ActionResult(
        approval_id=approved_action.approval_id,
        action=ACTION,
        resource_id=channel_id,
        before_state=before,
        after_state=after,
        verified=after is TARGET_STATE,
    )
