"""A write waiting for the operator, and the checks before signing it (extend_the_hub.md §4)."""

from datetime import datetime
from typing import Any

from pydantic import AwareDatetime, BaseModel

from media_ops_contracts.approved_action import ActionProposal
from media_ops_contracts.tool_failure import FailureKind, ToolFailure

PENDING_APPROVALS = "pending_approvals"  # agent.state key: tool use id -> PendingApproval


class PendingApproval(BaseModel):
    approval_id: str
    proposal: ActionProposal
    expires_at: AwareDatetime


def check_approval_decision(
    pending: PendingApproval, decision: dict[str, Any], current: ActionProposal, now: datetime
) -> ToolFailure | None:
    """None when an approved decision may be signed; otherwise why it may not."""
    if decision.get("actor_id") != pending.proposal.actor_id:
        return ToolFailure(
            FailureKind.APPROVAL_REQUIRED,
            "Only the operator who was asked can decide this approval.",
            "Ask that operator to decide, or propose the action again.",
        )
    if now >= pending.expires_at:
        return ToolFailure(
            FailureKind.APPROVAL_EXPIRED,
            "The approval request expired before the decision arrived.",
            "Propose the action again and decide within 10 minutes.",
        )
    if current != pending.proposal:
        return ToolFailure(
            FailureKind.APPROVAL_REQUIRED,
            "The pending action no longer matches what the operator approved.",
            "Propose the action again.",
        )
    return None


def read_pending_approvals(state: Any) -> dict[str, PendingApproval]:
    stored = state.get(PENDING_APPROVALS) or {}
    return {key: PendingApproval.model_validate(value) for key, value in stored.items()}


def write_pending_approvals(state: Any, pending: dict[str, PendingApproval]) -> None:
    state.set(PENDING_APPROVALS, {k: v.model_dump(mode="json") for k, v in pending.items()})
