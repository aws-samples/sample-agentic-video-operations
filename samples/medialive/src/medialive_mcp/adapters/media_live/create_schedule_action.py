"""Add one approved timed action (input switch, SCTE-35, pause, unpause) to a channel schedule."""

from typing import Any

from media_ops_contracts.action_result import ActionResult
from media_ops_contracts.approved_action import ApprovedAction
from media_ops_contracts.call_aws_operation import call_aws_operation
from media_ops_contracts.require_action_approval import require_action_approval
from media_ops_contracts.tool_failure import FailureKind, ToolFailure
from medialive_mcp.adapters.media_live.build_schedule_action import (
    SCHEDULE_CREATE_ACTIONS,
    build_schedule_action,
)
from medialive_mcp.adapters.media_live.describe_schedule import describe_schedule
from medialive_mcp.domain.write_requirements import (
    ApprovalCheck,
    VerificationPolicy,
    wait_for_condition,
)

TIMED_ACTIONS = SCHEDULE_CREATE_ACTIONS - {"switch_channel_input"}


def create_schedule_action(
    medialive: Any,
    approved_action: ApprovedAction,
    check: ApprovalCheck,
    policy: VerificationPolicy,
) -> ActionResult:
    """The approval names the action, so an approval for one action cannot run another."""
    if approved_action.action not in TIMED_ACTIONS:
        raise ToolFailure(
            FailureKind.APPROVAL_REQUIRED,
            f"{approved_action.action} is not a timed schedule action.",
            f"Use one of: {', '.join(sorted(TIMED_ACTIONS))}.",
        )
    require_action_approval(
        approved_action, action=approved_action.action, signing_key=check.signing_key, now=check.now
    )
    channel_id = approved_action.resource_id
    body = build_schedule_action(approved_action.action, approved_action.parameters)
    name = body["ActionName"]

    def is_scheduled() -> bool:
        return any(
            action.action_name == name for action in describe_schedule(medialive, channel_id)
        )

    before = is_scheduled()
    call_aws_operation(
        medialive,
        "batch_update_schedule",
        ChannelId=channel_id,
        Creates={"ScheduleActions": [body]},
    )
    after = wait_for_condition(is_scheduled, bool, policy)
    return ActionResult(
        approval_id=approved_action.approval_id,
        action=approved_action.action,
        resource_id=channel_id,
        before_state="scheduled" if before else "absent",
        after_state="scheduled" if after else "absent",
        verified=after,
    )
