from datetime import UTC, datetime, timedelta

import pytest

from media_ops_contracts.approved_action import ActionProposal, sign_approved_action
from media_ops_contracts.require_signed_parameters import require_signed_parameters
from media_ops_contracts.tool_failure import FailureKind, ToolFailure

KEY = b"test-signing-key"
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def approve(parameters: dict[str, str]):
    proposal = ActionProposal(
        actor_id="operator-1",
        action="switch_channel_input",
        resource_id="1234567",
        parameters=parameters,
    )
    return sign_approved_action(
        proposal, approval_id="ap-1", expires_at=NOW + timedelta(minutes=10), signing_key=KEY
    )


SIGNED = approve({"input_attachment": "demo-backup-srt", "action_name": "to-backup"})


def test_accepts_the_inputs_the_operator_signed():
    require_signed_parameters(
        SIGNED, {"input_attachment": "demo-backup-srt", "action_name": "to-backup"}
    )


def test_compares_inputs_as_the_proposal_recorded_them():
    """The hook signs str(value) and drops None, so the check does the same."""
    require_signed_parameters(approve({"version": "2"}), {"version": 2, "note": None})


def test_accepts_no_parameters_when_none_were_signed():
    require_signed_parameters(approve({}), {})


@pytest.mark.parametrize(
    ("expected", "named"),
    [
        ({"input_attachment": "demo-primary-srt", "action_name": "to-backup"}, "input_attachment"),
        ({"input_attachment": "demo-backup-srt"}, "action_name"),
        (
            {"input_attachment": "demo-backup-srt", "action_name": "to-backup", "extra": "1"},
            "extra",
        ),
    ],
    ids=["a-changed-value", "a-signed-input-not-passed", "an-input-not-signed"],
)
def test_refuses_inputs_that_differ_from_the_signed_ones(expected, named):
    with pytest.raises(ToolFailure) as failure:
        require_signed_parameters(SIGNED, expected)

    assert failure.value.kind is FailureKind.APPROVAL_REQUIRED
    assert named in failure.value.message
    assert "demo-" not in failure.value.message  # names the inputs, never echoes their values
    assert failure.value.next_action


def test_refuses_a_signed_parameter_when_the_write_takes_none():
    with pytest.raises(ToolFailure) as failure:
        require_signed_parameters(approve({"unexpected": "value"}), {})

    assert failure.value.kind is FailureKind.APPROVAL_REQUIRED
    assert "unexpected" in failure.value.message
