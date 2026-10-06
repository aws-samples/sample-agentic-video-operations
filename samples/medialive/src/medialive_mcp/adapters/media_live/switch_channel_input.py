"""Switch an approved channel to another input now, and verify every pipeline uses it."""

from typing import Any

from media_ops_contracts.action_result import ActionResult
from media_ops_contracts.approved_action import ApprovedAction
from media_ops_contracts.call_aws_operation import call_aws_operation
from media_ops_contracts.require_action_approval import require_action_approval
from medialive_mcp.adapters.media_live.build_schedule_action import build_schedule_action
from medialive_mcp.adapters.media_live.describe_channel import describe_channel
from medialive_mcp.domain.write_requirements import (
    ApprovalCheck,
    VerificationPolicy,
    wait_for_condition,
)

ACTION = "switch_channel_input"


def switch_channel_input(
    medialive: Any,
    approved_action: ApprovedAction,
    check: ApprovalCheck,
    policy: VerificationPolicy,
) -> ActionResult:
    require_action_approval(
        approved_action, action=ACTION, signing_key=check.signing_key, now=check.now
    )
    channel_id = approved_action.resource_id
    body = build_schedule_action(ACTION, approved_action.parameters)
    target = approved_action.parameters["input_attachment"]

    def active_inputs() -> list[str | None]:
        pipelines = describe_channel(medialive, channel_id).pipelines
        return [pipeline.active_input_attachment for pipeline in pipelines]

    before = active_inputs()
    call_aws_operation(
        medialive,
        "batch_update_schedule",
        ChannelId=channel_id,
        Creates={"ScheduleActions": [body]},
    )
    after = wait_for_condition(
        active_inputs, lambda inputs: bool(inputs) and all(i == target for i in inputs), policy
    )
    return ActionResult(
        approval_id=approved_action.approval_id,
        action=ACTION,
        resource_id=channel_id,
        before_state=",".join(str(i) for i in before),
        after_state=",".join(str(i) for i in after),
        verified=bool(after) and all(i == target for i in after),
    )
