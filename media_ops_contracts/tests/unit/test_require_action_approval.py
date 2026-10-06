from datetime import UTC, datetime, timedelta

import pytest

from media_ops_contracts.approved_action import ActionProposal, sign_approved_action
from media_ops_contracts.require_action_approval import require_action_approval
from media_ops_contracts.tool_failure import FailureKind, ToolFailure

KEY = b"test-signing-key"
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
PROPOSAL = ActionProposal(actor_id="operator-1", action="stop_channel", resource_id="1234567")


def approve(proposal=PROPOSAL, *, expires_at=NOW + timedelta(minutes=10), key=KEY):
    return sign_approved_action(
        proposal, approval_id="ap-1", expires_at=expires_at, signing_key=key
    )


def check(approved, **overrides):
    arguments = {"action": "stop_channel", "signing_key": KEY, "now": NOW} | overrides
    require_action_approval(approved, **arguments)


def assert_rejected(kind, approved, **overrides):
    with pytest.raises(ToolFailure) as failure:
        check(approved, **overrides)
    assert failure.value.kind is kind
    assert failure.value.next_action


def test_accepts_signed_approval_for_the_same_action_and_resource():
    check(approve(), resource_id="1234567")


def test_rejects_missing_approval():
    assert_rejected(FailureKind.APPROVAL_REQUIRED, None)


def test_rejects_approval_for_another_action():
    assert_rejected(FailureKind.APPROVAL_REQUIRED, approve(), action="start_channel")


def test_rejects_approval_for_another_channel():
    assert_rejected(FailureKind.APPROVAL_REQUIRED, approve(), resource_id="7654321")


def test_rejects_approval_signed_with_another_key():
    assert_rejected(FailureKind.APPROVAL_REQUIRED, approve(key=b"attacker-key"))


def test_rejects_approval_whose_parameters_changed_after_signing():
    tampered = approve().model_copy(update={"parameters": {"input": "backup"}})
    assert_rejected(FailureKind.APPROVAL_REQUIRED, tampered)


def test_rejects_expired_approval():
    assert_rejected(FailureKind.APPROVAL_EXPIRED, approve(expires_at=NOW))


def test_signature_survives_a_json_round_trip_between_runtimes():
    approved = approve()
    received = type(approved).model_validate_json(approved.model_dump_json())
    check(received, resource_id="1234567")


def test_rejects_a_naive_now_with_a_classified_failure():
    assert_rejected(FailureKind.INVALID_REQUEST, approve(), now=NOW.replace(tzinfo=None))
