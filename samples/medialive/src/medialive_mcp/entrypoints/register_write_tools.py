"""MediaLive write tools for the MCP server; registered only with ALLOW_WRITES=true.

Each tool needs `confirm_resource_id` equal to the channel id. The MCP client's own
tool-approval prompt is the human approval; the adapters verify every change (§9).
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from fastmcp import FastMCP

from media_ops_contracts.action_result import ActionResult
from media_ops_contracts.approved_action import (
    APPROVAL_LIFETIME,
    ActionProposal,
    ApprovedAction,
    sign_approved_action,
)
from media_ops_contracts.tool_failure import FailureKind, ToolFailure
from medialive_mcp.adapters.media_live.create_schedule_action import create_schedule_action
from medialive_mcp.adapters.media_live.delete_schedule_action import delete_schedule_action
from medialive_mcp.adapters.media_live.start_channel import start_channel
from medialive_mcp.adapters.media_live.stop_channel import stop_channel
from medialive_mcp.adapters.media_live.switch_channel_input import switch_channel_input
from medialive_mcp.bootstrap.create_medialive_clients import MediaLiveClients
from medialive_mcp.domain.write_requirements import ApprovalCheck, VerificationPolicy
from medialive_mcp.entrypoints.report_tool_failures import report_tool_failures

DESTRUCTIVE = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True}


def register_write_tools(
    mcp: FastMCP, clients: MediaLiveClients, channel: Callable, signing_key: bytes
) -> None:
    def run(action: str, channel_id: str | None, confirm: str, parameters: dict, adapter: Callable):
        now = datetime.now(UTC)
        approved = approve_locally(action, channel(channel_id), confirm, parameters, signing_key)
        return adapter(clients.medialive, approved, ApprovalCheck(signing_key, now), POLICY)

    @mcp.tool(name="start_channel", annotations=DESTRUCTIVE)
    @report_tool_failures
    def start_channel_tool(channel_id: str, confirm_resource_id: str) -> ActionResult:
        """Start a channel (billable). confirm_resource_id must repeat channel_id."""
        return run("start_channel", channel_id, confirm_resource_id, {}, start_channel)

    @mcp.tool(name="stop_channel", annotations=DESTRUCTIVE)
    @report_tool_failures
    def stop_channel_tool(channel_id: str, confirm_resource_id: str) -> ActionResult:
        """Stop a channel: its outputs go off air. confirm_resource_id must repeat channel_id."""
        return run("stop_channel", channel_id, confirm_resource_id, {}, stop_channel)

    @mcp.tool(name="switch_channel_input", annotations=DESTRUCTIVE)
    @report_tool_failures
    def switch_channel_input_tool(
        channel_id: str, input_attachment: str, confirm_resource_id: str
    ) -> ActionResult:
        """Switch every pipeline to `input_attachment` now, then verify it is active."""
        name = f"switch-{input_attachment}-{datetime.now(UTC):%H%M%S}"
        parameters = {"action_name": name, "input_attachment": input_attachment}
        return run(
            "switch_channel_input",
            channel_id,
            confirm_resource_id,
            parameters,
            switch_channel_input,
        )

    @mcp.tool(annotations=DESTRUCTIVE)
    @report_tool_failures
    def create_input_switch_action(
        channel_id: str,
        action_name: str,
        input_attachment: str,
        start_time: str,
        confirm_resource_id: str,
    ) -> ActionResult:
        """Schedule an input switch at start_time (ISO 8601, UTC)."""
        parameters = {
            "action_name": action_name, "input_attachment": input_attachment,
            "start_time": start_time,
        }  # fmt: skip
        return run(
            "create_input_switch_action", channel_id, confirm_resource_id, parameters,
            create_schedule_action,
        )  # fmt: skip

    @mcp.tool(annotations=DESTRUCTIVE)
    @report_tool_failures
    def create_scte35_action(
        channel_id: str,
        action_name: str,
        start_time: str,
        splice_event_id: int,
        confirm_resource_id: str,
        duration: int | None = None,
    ) -> ActionResult:
        """Schedule a SCTE-35 splice insert (ad break) at start_time."""
        parameters = {
            "action_name": action_name, "start_time": start_time,
            "splice_event_id": str(splice_event_id), "duration": str(duration or ""),
        }  # fmt: skip
        return run(
            "create_scte35_action", channel_id, confirm_resource_id, parameters,
            create_schedule_action,
        )  # fmt: skip

    for action, verb in (("create_pause_action", "Pause"), ("create_unpause_action", "Unpause")):
        register_pipeline_state_tool(mcp, run, action, verb)

    @mcp.tool(name="delete_schedule_action", annotations=DESTRUCTIVE)
    @report_tool_failures
    def delete_schedule_action_tool(
        channel_id: str, action_name: str, confirm_resource_id: str
    ) -> ActionResult:
        """Delete one scheduled action by name and verify it is gone."""
        parameters = {"action_name": action_name}
        return run(
            "delete_schedule_action", channel_id, confirm_resource_id, parameters,
            delete_schedule_action,
        )  # fmt: skip


def register_pipeline_state_tool(mcp: FastMCP, run: Callable, action: str, verb: str) -> None:
    def pipeline_state_tool(
        channel_id: str,
        action_name: str,
        start_time: str,
        pipeline_id: str,
        confirm_resource_id: str,
    ) -> ActionResult:
        parameters = {
            "action_name": action_name, "start_time": start_time, "pipeline_id": pipeline_id,
        }  # fmt: skip
        return run(action, channel_id, confirm_resource_id, parameters, create_schedule_action)

    pipeline_state_tool.__doc__ = f"{verb} one pipeline (PIPELINE_0 or PIPELINE_1) at start_time."
    mcp.tool(report_tool_failures(pipeline_state_tool), name=action, annotations=DESTRUCTIVE)


POLICY = VerificationPolicy()


def approve_locally(
    action: str, channel_id: str, confirm_resource_id: str, parameters: dict, signing_key: bytes
) -> ApprovedAction:
    """Bind the MCP client's approval to exactly this channel, action and parameters."""
    if confirm_resource_id != channel_id:
        raise ToolFailure(
            FailureKind.APPROVAL_REQUIRED,
            f"confirm_resource_id ({confirm_resource_id}) does not match channel {channel_id}.",
            "Repeat the exact channel id in confirm_resource_id.",
        )
    proposal = ActionProposal(
        actor_id="mcp-client", action=action, resource_id=channel_id, parameters=parameters
    )
    return sign_approved_action(
        proposal,
        approval_id=str(uuid.uuid4()),
        expires_at=datetime.now(UTC) + APPROVAL_LIFETIME,
        signing_key=signing_key,
    )
