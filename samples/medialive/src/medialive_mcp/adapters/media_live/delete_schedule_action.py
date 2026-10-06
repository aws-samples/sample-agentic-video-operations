"""Remove one approved action from a channel schedule and verify it is gone."""

from typing import Any

from media_ops_contracts.approved_action import ApprovedAction
from media_ops_contracts.call_aws_operation import call_aws_operation
from media_ops_contracts.require_action_approval import require_action_approval
from media_ops_contracts.tool_failure import FailureKind, ToolFailure
from medialive_mcp.adapters.media_live.describe_schedule import describe_schedule
from medialive_mcp.adapters.media_live.media_live_records import ActionResult
from medialive_mcp.domain.write_requirements import (
    ApprovalCheck,
    VerificationPolicy,
    wait_for_condition,
)

ACTION = "delete_schedule_action"


def delete_schedule_action(
    medialive: Any,
    approved_action: ApprovedAction,
    check: ApprovalCheck,
    policy: VerificationPolicy,
) -> ActionResult:
    require_action_approval(
        approved_action, action=ACTION, signing_key=check.signing_key, now=check.now
    )
    channel_id = approved_action.resource_id
    name = approved_action.parameters.get("action_name", "")
    if not name:
        raise ToolFailure(FailureKind.INVALID_REQUEST, "action_name is required.", "Name it.")

    def is_scheduled() -> bool:
        return any(
            action.action_name == name for action in describe_schedule(medialive, channel_id)
        )

    before = is_scheduled()
    call_aws_operation(
        medialive, "batch_update_schedule", ChannelId=channel_id, Deletes={"ActionNames": [name]}
    )
    still_scheduled = wait_for_condition(is_scheduled, lambda present: not present, policy)
    return ActionResult(
        approval_id=approved_action.approval_id,
        action=ACTION,
        resource_id=channel_id,
        before_state="scheduled" if before else "absent",
        after_state="scheduled" if still_scheduled else "absent",
        verified=not still_scheduled,
    )
