"""The medialive write tools of the domain pack (extend_the_hub.md §2, §4).

Each function takes the inputs the model proposes plus `approved_action`, which the hub's
approval hook injects after the operator approves. The function refuses an approval for
other inputs, then the adapter checks signature and expiry, acts once and verifies.
"""

from datetime import UTC, datetime

from media_ops_contracts.action_result import ActionResult
from media_ops_contracts.approved_action import ApprovedAction
from media_ops_contracts.domain_pack import WriteTool
from media_ops_contracts.resolve_approval_signing_key import resolve_approval_signing_key
from media_ops_contracts.tool_failure import FailureKind, ToolFailure
from medialive_mcp.adapters.media_live import create_schedule_action as schedule_create
from medialive_mcp.adapters.media_live import delete_schedule_action as schedule_delete
from medialive_mcp.adapters.media_live import start_channel as start_adapter
from medialive_mcp.adapters.media_live import stop_channel as stop_adapter
from medialive_mcp.adapters.media_live import switch_channel_input as switch_adapter
from medialive_mcp.bootstrap.create_medialive_clients import MediaLiveClients
from medialive_mcp.domain.write_requirements import ApprovalCheck, VerificationPolicy
from medialive_mcp.settings.runtime_settings import RuntimeSettings

VERIFICATION = VerificationPolicy()


def require_matching_approval(
    approved_action: ApprovedAction, channel_id: str, proposed: dict[str, object]
) -> None:
    """The approval must name this channel and exactly these proposed inputs."""
    expected = {name: str(value) for name, value in proposed.items() if value is not None}
    if approved_action.resource_id != channel_id or approved_action.parameters != expected:
        raise ToolFailure(
            FailureKind.APPROVAL_REQUIRED,
            "The approval does not match this channel and these inputs.",
            "Propose the action again and ask the operator to approve it.",
        )


def create_write_tools(settings: RuntimeSettings, clients: MediaLiveClients) -> list[WriteTool]:
    signing_key = resolve_approval_signing_key(settings.approval_signing_key)

    def check() -> ApprovalCheck:
        return ApprovalCheck(signing_key=signing_key, now=datetime.now(UTC))

    def start_channel(channel_id: str, approved_action: ApprovedAction) -> ActionResult:
        """Start a channel (billable), then verify it is RUNNING. Needs operator approval."""
        require_matching_approval(approved_action, channel_id, {})
        return start_adapter.start_channel(
            clients.medialive, approved_action, check(), VERIFICATION
        )

    def stop_channel(channel_id: str, approved_action: ApprovedAction) -> ActionResult:
        """Stop a channel (outputs go off air), then verify IDLE. Needs operator approval."""
        require_matching_approval(approved_action, channel_id, {})
        return stop_adapter.stop_channel(clients.medialive, approved_action, check(), VERIFICATION)

    def switch_channel_input(
        channel_id: str, action_name: str, input_attachment: str, approved_action: ApprovedAction
    ) -> ActionResult:
        """Switch every pipeline to input_attachment now, then verify. Needs operator approval."""
        proposed = {"action_name": action_name, "input_attachment": input_attachment}
        require_matching_approval(approved_action, channel_id, proposed)
        return switch_adapter.switch_channel_input(
            clients.medialive, approved_action, check(), VERIFICATION
        )

    def create_input_switch_action(
        channel_id: str,
        action_name: str,
        input_attachment: str,
        start_time: str,
        approved_action: ApprovedAction,
    ) -> ActionResult:
        """Schedule an input switch at start_time (ISO 8601, UTC). Needs operator approval."""
        proposed = {
            "action_name": action_name, "input_attachment": input_attachment,
            "start_time": start_time,
        }  # fmt: skip
        require_matching_approval(approved_action, channel_id, proposed)
        return schedule_create.create_schedule_action(
            clients.medialive, approved_action, check(), VERIFICATION
        )

    def create_scte35_action(
        channel_id: str,
        action_name: str,
        start_time: str,
        splice_event_id: int,
        approved_action: ApprovedAction,
        duration: int | None = None,
    ) -> ActionResult:
        """Schedule a SCTE-35 splice insert (ad break) at start_time. Needs operator approval."""
        proposed = {
            "action_name": action_name, "start_time": start_time,
            "splice_event_id": splice_event_id, "duration": duration,
        }  # fmt: skip
        require_matching_approval(approved_action, channel_id, proposed)
        return schedule_create.create_schedule_action(
            clients.medialive, approved_action, check(), VERIFICATION
        )

    def delete_schedule_action(
        channel_id: str, action_name: str, approved_action: ApprovedAction
    ) -> ActionResult:
        """Delete one scheduled action by name, then verify it is gone. Needs approval."""
        require_matching_approval(approved_action, channel_id, {"action_name": action_name})
        return schedule_delete.delete_schedule_action(
            clients.medialive, approved_action, check(), VERIFICATION
        )

    pipeline_tools = [
        create_pipeline_state_tool(action, clients, check)
        for action in ("create_pause_action", "create_unpause_action")
    ]
    functions = [
        start_channel,
        stop_channel,
        switch_channel_input,
        create_input_switch_action,
        create_scte35_action,
        *pipeline_tools,
        delete_schedule_action,
    ]
    return [WriteTool(function=function, resource_parameter="channel_id") for function in functions]


def create_pipeline_state_tool(action: str, clients: MediaLiveClients, check):
    verb = "Pause" if action == "create_pause_action" else "Unpause"

    def pipeline_state_tool(
        channel_id: str,
        action_name: str,
        start_time: str,
        pipeline_id: str,
        approved_action: ApprovedAction,
    ) -> ActionResult:
        proposed = {
            "action_name": action_name,
            "start_time": start_time,
            "pipeline_id": pipeline_id,
        }
        require_matching_approval(approved_action, channel_id, proposed)
        return schedule_create.create_schedule_action(
            clients.medialive, approved_action, check(), VERIFICATION
        )

    pipeline_state_tool.__name__ = action
    pipeline_state_tool.__doc__ = (
        f"{verb} one pipeline (PIPELINE_0 or PIPELINE_1) at start_time. Needs operator approval."
    )
    return pipeline_state_tool
