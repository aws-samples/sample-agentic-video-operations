"""MediaLive write tools for the MCP server; registered only with ALLOW_WRITES=true.

Before any change, the server asks the MCP client's user, by elicitation, to type the
exact channel id (confirm_with_operator); the model's arguments can't answer for them,
though a client that answers elicitations by itself can (a trusted client is assumed).
The adapters then verify every change (§9).
"""

import asyncio
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from fastmcp import Context, FastMCP

from media_ops_contracts.action_result import ActionResult
from media_ops_contracts.approved_action import (
    APPROVAL_LIFETIME,
    ActionProposal,
    ApprovedAction,
    sign_approved_action,
)
from medialive_mcp.adapters.media_live.create_schedule_action import create_schedule_action
from medialive_mcp.adapters.media_live.delete_schedule_action import delete_schedule_action
from medialive_mcp.adapters.media_live.start_channel import start_channel
from medialive_mcp.adapters.media_live.stop_channel import stop_channel
from medialive_mcp.adapters.media_live.switch_channel_input import switch_channel_input
from medialive_mcp.bootstrap.create_medialive_clients import MediaLiveClients
from medialive_mcp.domain.write_requirements import ApprovalCheck, VerificationPolicy
from medialive_mcp.entrypoints.confirm_with_operator import confirm_with_operator
from medialive_mcp.entrypoints.report_tool_failures import report_tool_failures

DESTRUCTIVE = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True}


def register_write_tools(
    mcp: FastMCP, clients: MediaLiveClients, channel: Callable, signing_key: bytes
) -> None:
    async def run(
        ctx: Context, action: str, channel_id: str | None, parameters: dict, adapter: Callable
    ) -> ActionResult:
        resource_id = channel(channel_id)
        await confirm_with_operator(
            ctx,
            action=action,
            resource_label="channel id",
            resource_id=resource_id,
            parameters=parameters,
        )
        approved = approve_locally(action, resource_id, parameters, signing_key)
        check = ApprovalCheck(signing_key, datetime.now(UTC))
        # The adapters poll until the change is verified; keep the server responsive meanwhile.
        return await asyncio.to_thread(adapter, clients.medialive, approved, check, POLICY)

    @mcp.tool(name="start_channel", annotations=DESTRUCTIVE)
    @report_tool_failures
    async def start_channel_tool(channel_id: str, ctx: Context) -> ActionResult:
        """Start a channel (billable). The operator types the exact channel id first."""
        return await run(ctx, "start_channel", channel_id, {}, start_channel)

    @mcp.tool(name="stop_channel", annotations=DESTRUCTIVE)
    @report_tool_failures
    async def stop_channel_tool(channel_id: str, ctx: Context) -> ActionResult:
        """Stop a channel: its outputs go off air. The operator types the exact channel id first."""
        return await run(ctx, "stop_channel", channel_id, {}, stop_channel)

    @mcp.tool(name="switch_channel_input", annotations=DESTRUCTIVE)
    @report_tool_failures
    async def switch_channel_input_tool(
        channel_id: str, input_attachment: str, ctx: Context
    ) -> ActionResult:
        """Switch every pipeline to `input_attachment` now, then verify it is active."""
        name = f"switch-{input_attachment}-{datetime.now(UTC):%H%M%S}"
        parameters = {"action_name": name, "input_attachment": input_attachment}
        return await run(ctx, "switch_channel_input", channel_id, parameters, switch_channel_input)

    @mcp.tool(annotations=DESTRUCTIVE)
    @report_tool_failures
    async def create_input_switch_action(
        channel_id: str,
        action_name: str,
        input_attachment: str,
        start_time: str,
        ctx: Context,
    ) -> ActionResult:
        """Schedule an input switch at start_time (ISO 8601, UTC)."""
        parameters = {
            "action_name": action_name, "input_attachment": input_attachment,
            "start_time": start_time,
        }  # fmt: skip
        return await run(
            ctx, "create_input_switch_action", channel_id, parameters, create_schedule_action
        )

    @mcp.tool(annotations=DESTRUCTIVE)
    @report_tool_failures
    async def create_scte35_action(
        channel_id: str,
        action_name: str,
        start_time: str,
        splice_event_id: int,
        ctx: Context,
        duration: int | None = None,
    ) -> ActionResult:
        """Schedule a SCTE-35 splice insert (ad break) at start_time."""
        parameters = {
            "action_name": action_name, "start_time": start_time,
            "splice_event_id": str(splice_event_id), "duration": str(duration or ""),
        }  # fmt: skip
        return await run(
            ctx, "create_scte35_action", channel_id, parameters, create_schedule_action
        )

    for action, verb in (("create_pause_action", "Pause"), ("create_unpause_action", "Unpause")):
        register_pipeline_state_tool(mcp, run, action, verb)

    @mcp.tool(name="delete_schedule_action", annotations=DESTRUCTIVE)
    @report_tool_failures
    async def delete_schedule_action_tool(
        channel_id: str, action_name: str, ctx: Context
    ) -> ActionResult:
        """Delete one scheduled action by name and verify it is gone."""
        parameters = {"action_name": action_name}
        return await run(
            ctx, "delete_schedule_action", channel_id, parameters, delete_schedule_action
        )


def register_pipeline_state_tool(mcp: FastMCP, run: Callable, action: str, verb: str) -> None:
    async def pipeline_state_tool(
        channel_id: str,
        action_name: str,
        start_time: str,
        pipeline_id: str,
        ctx: Context,
    ) -> ActionResult:
        parameters = {
            "action_name": action_name, "start_time": start_time, "pipeline_id": pipeline_id,
        }  # fmt: skip
        return await run(ctx, action, channel_id, parameters, create_schedule_action)

    pipeline_state_tool.__doc__ = f"{verb} one pipeline (PIPELINE_0 or PIPELINE_1) at start_time."
    mcp.tool(report_tool_failures(pipeline_state_tool), name=action, annotations=DESTRUCTIVE)


POLICY = VerificationPolicy()


def approve_locally(
    action: str, channel_id: str, parameters: dict, signing_key: bytes
) -> ApprovedAction:
    """Sign what the operator just confirmed: exactly this channel, action and parameters."""
    proposal = ActionProposal(
        actor_id="mcp-client", action=action, resource_id=channel_id, parameters=parameters
    )
    return sign_approved_action(
        proposal,
        approval_id=str(uuid.uuid4()),
        expires_at=datetime.now(UTC) + APPROVAL_LIFETIME,
        signing_key=signing_key,
    )
