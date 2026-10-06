"""Create approval-bound MediaConnect writes for the domain pack."""

from collections.abc import Callable
from datetime import datetime

from media_ops_contracts.action_result import ActionResult
from media_ops_contracts.approved_action import ApprovedAction
from media_ops_contracts.domain_pack import WriteTool
from media_ops_contracts.read_utc_now import read_utc_now
from media_ops_contracts.require_signed_parameters import require_signed_parameters
from media_ops_contracts.resolve_approval_signing_key import resolve_approval_signing_key
from media_ops_contracts.tool_failure import FailureKind, ToolFailure
from mediaconnect_mcp.adapters.media_connect import start_flow as start_adapter
from mediaconnect_mcp.adapters.media_connect import stop_flow as stop_adapter
from mediaconnect_mcp.adapters.media_connect.verify_flow_state import FlowActionResult
from mediaconnect_mcp.bootstrap.create_mediaconnect_clients import MediaConnectClients
from mediaconnect_mcp.settings.runtime_settings import RuntimeSettings


def require_matching_approval(approved_action: ApprovedAction, action: str, flow_arn: str) -> None:
    """The approval must name this flow action, and sign no inputs: start and stop take none."""
    if approved_action.action != action or approved_action.resource_id != flow_arn:
        raise ToolFailure(
            FailureKind.APPROVAL_REQUIRED,
            "The approval does not match this flow action.",
            "Propose the action again and ask the operator to approve it.",
        )
    require_signed_parameters(approved_action, {})


def create_write_tools(
    settings: RuntimeSettings,
    clients: MediaConnectClients,
    *,
    clock: Callable[[], datetime] = read_utc_now,
) -> list[WriteTool]:
    signing_key = resolve_approval_signing_key(settings.approval_signing_key.get_secret_value())

    def start_flow(flow_arn: str, approved_action: ApprovedAction) -> ActionResult:
        """Start a flow (billable), then verify it is ACTIVE. Needs operator approval."""
        require_matching_approval(approved_action, "start_flow", flow_arn)
        result = start_adapter.start_flow(
            approved_action,
            clients.mediaconnect,
            signing_key,
            clock(),
        )
        return translate_action_result(result, approved_action.approval_id)

    def stop_flow(flow_arn: str, approved_action: ApprovedAction) -> ActionResult:
        """Stop a flow (transport ends), then verify STANDBY. Needs operator approval."""
        require_matching_approval(approved_action, "stop_flow", flow_arn)
        result = stop_adapter.stop_flow(
            approved_action,
            clients.mediaconnect,
            signing_key,
            clock(),
        )
        return translate_action_result(result, approved_action.approval_id)

    return [
        WriteTool(function=start_flow, resource_parameter="flow_arn"),
        WriteTool(function=stop_flow, resource_parameter="flow_arn"),
    ]


def translate_action_result(result: FlowActionResult, approval_id: str) -> ActionResult:
    return ActionResult(
        approval_id=approval_id,
        action=result.action,
        resource_id=result.resource_id,
        before_state=result.before.state,
        after_state=result.after.state,
        verified=result.verified,
    )
