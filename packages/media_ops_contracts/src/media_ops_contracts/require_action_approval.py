"""Reject writes that are not approved for exactly this action (write_safe_tools.md §3)."""

import hmac
from datetime import datetime
from typing import NoReturn

from media_ops_contracts.approved_action import ApprovedAction, compute_approval_signature
from media_ops_contracts.tool_failure import FailureKind, ToolFailure

_ASK_FOR_APPROVAL = "Ask the operator to approve this exact action, then retry."


def require_action_approval(
    approved_action: ApprovedAction | None,
    *,
    action: str,
    signing_key: bytes,
    now: datetime,
    resource_id: str | None = None,
) -> None:
    """Raise ToolFailure unless `approved_action` authorizes `action` (on `resource_id`) now."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ToolFailure(
            FailureKind.INVALID_REQUEST,
            "require_action_approval needs a timezone-aware `now`.",
            "Pass datetime.now(UTC) or another aware datetime.",
        )
    if approved_action is None:
        _reject(f"{action} needs an approved action.")
    if approved_action.action != action:
        _reject(f"Approval is for {approved_action.action}, not {action}.")
    if resource_id is not None and approved_action.resource_id != resource_id:
        _reject(f"Approval is for resource {approved_action.resource_id}, not {resource_id}.")
    expected = compute_approval_signature(approved_action.model_dump(mode="json"), signing_key)
    if not hmac.compare_digest(expected, approved_action.signature):
        _reject("Approval signature is not valid.")
    if now >= approved_action.expires_at:
        raise ToolFailure(
            FailureKind.APPROVAL_EXPIRED,
            f"Approval {approved_action.approval_id} expired.",
            _ASK_FOR_APPROVAL,
        )


def _reject(message: str) -> NoReturn:
    raise ToolFailure(FailureKind.APPROVAL_REQUIRED, message, _ASK_FOR_APPROVAL)
