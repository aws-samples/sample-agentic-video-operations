"""The checks before signing, and the adapter's second line (extend_the_hub.md §4)."""

from datetime import UTC, datetime, timedelta

import pytest
from channel_test_pack import SIGNING_KEY, ChannelTestPack
from media_ops_contracts.approved_action import ActionProposal, sign_approved_action
from media_ops_contracts.tool_failure import FailureKind, ToolFailure

from media_ops_hub.domain.pending_approval import PendingApproval, check_approval_decision

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
PROPOSAL = ActionProposal(
    actor_id="operator-a", action="stop_channel", resource_id="ch-1", parameters={"reason": "x"}
)
PENDING = PendingApproval(
    approval_id="approval-1", proposal=PROPOSAL, expires_at=NOW + timedelta(minutes=10)
)
APPROVE = {"approve": True, "actor_id": "operator-a"}


def test_a_timely_decision_on_the_same_call_may_be_signed():
    assert check_approval_decision(PENDING, APPROVE, PROPOSAL, NOW) is None


@pytest.mark.parametrize(
    "changed",
    [
        {"action": "start_channel"},
        {"resource_id": "ch-2"},
        {"parameters": {"reason": "y"}},
    ],
)
def test_a_changed_action_resource_or_parameters_is_refused(changed):
    current = PROPOSAL.model_copy(update=changed)

    failure = check_approval_decision(PENDING, APPROVE, current, NOW)

    assert failure.kind is FailureKind.APPROVAL_REQUIRED


def test_a_decision_at_the_deadline_is_expired():
    failure = check_approval_decision(PENDING, APPROVE, PROPOSAL, PENDING.expires_at)

    assert failure.kind is FailureKind.APPROVAL_EXPIRED


def test_the_adapter_refuses_an_expired_approved_action():
    pack = ChannelTestPack(now=lambda: NOW)
    [stop] = pack.write_tools()
    expired = sign_approved_action(
        PROPOSAL, approval_id="approval-1", expires_at=NOW, signing_key=SIGNING_KEY.encode()
    )

    with pytest.raises(ToolFailure) as raised:
        stop.function(channel_id="ch-1", approved_action=expired, reason="x")

    assert raised.value.kind is FailureKind.APPROVAL_EXPIRED
    assert pack.approvals == []
