import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from media_ops_contracts.approved_action import ActionProposal, sign_approved_action
from media_ops_contracts.replay_fixture_client import ReplayFixtureClient
from media_ops_contracts.tool_failure import FailureKind, ToolFailure
from mediaconnect_mcp.adapters.media_connect.describe_flow import FlowState
from mediaconnect_mcp.adapters.media_connect.start_flow import start_flow
from mediaconnect_mcp.adapters.media_connect.stop_flow import stop_flow
from mediaconnect_mcp.adapters.media_connect.verify_flow_state import FlowPoller

KEY = b"test-signing-key"
OTHER_KEY = b"another-signing-key"
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
FLOW_ARN = "arn:aws:mediaconnect:us-west-2:111122223333:flow:demo-flow:flow-1"
OTHER_FLOW_ARN = "arn:aws:mediaconnect:us-west-2:111122223333:flow:other-flow:flow-2"


def approve(
    action,
    *,
    resource_id=FLOW_ARN,
    signing_key=KEY,
    expires_at=NOW + timedelta(minutes=10),
):
    return sign_approved_action(
        ActionProposal(actor_id="operator-1", action=action, resource_id=resource_id),
        approval_id="approval-1",
        expires_at=expires_at,
        signing_key=signing_key,
    )


def replay_write(fixtures_dir, action, before, after):
    scenario = fixtures_dir / f"{action}_flow"
    scenario.mkdir()
    describe_responses = {
        "sequence": [
            {"Flow": {"FlowArn": FLOW_ARN, "Name": "demo-flow", "Status": before}},
            {"Flow": {"FlowArn": FLOW_ARN, "Name": "demo-flow", "Status": after}},
        ]
    }
    (scenario / "mediaconnect.describe_flow.json").write_text(json.dumps(describe_responses))
    (scenario / f"mediaconnect.{action}_flow.json").write_text("{}")
    return ReplayFixtureClient("mediaconnect", scenario=scenario.name, fixtures_dir=fixtures_dir)


def assert_rejected(expected_kind, action, approved_action):
    client = ReplayFixtureClient(
        "mediaconnect",
        scenario="unused",
        fixtures_dir=Path("fixtures"),
    )
    write = stop_flow if action == "stop" else start_flow
    with pytest.raises(ToolFailure) as failure:
        write(approved_action, client, KEY, NOW)
    assert failure.value.kind is expected_kind
    assert failure.value.next_action
    assert client.calls == []


def test_stop_flow_rejects_missing_approval():
    assert_rejected(FailureKind.APPROVAL_REQUIRED, "stop", None)


def test_stop_flow_rejects_approval_for_another_flow():
    tampered = approve("stop_flow").model_copy(update={"resource_id": OTHER_FLOW_ARN})
    assert_rejected(FailureKind.APPROVAL_REQUIRED, "stop", tampered)


def test_stop_flow_rejects_approval_for_another_action():
    assert_rejected(FailureKind.APPROVAL_REQUIRED, "stop", approve("start_flow"))


def test_stop_flow_rejects_expired_approval():
    assert_rejected(
        FailureKind.APPROVAL_EXPIRED,
        "stop",
        approve("stop_flow", expires_at=NOW),
    )


def test_stop_flow_rejects_bad_signature():
    assert_rejected(
        FailureKind.APPROVAL_REQUIRED,
        "stop",
        approve("stop_flow", signing_key=OTHER_KEY),
    )


def test_stop_flow_returns_verified_before_and_after_states(tmp_path):
    client = replay_write(tmp_path, "stop", "ACTIVE", "STANDBY")

    result = stop_flow(approve("stop_flow"), client, KEY, NOW)

    assert result.before.state is FlowState.ACTIVE
    assert result.after.state is FlowState.STANDBY
    assert result.verified is True
    assert ("stop_flow", {"FlowArn": FLOW_ARN}) in client.calls


def test_start_flow_rejects_missing_approval():
    assert_rejected(FailureKind.APPROVAL_REQUIRED, "start", None)


def test_start_flow_rejects_approval_for_another_flow():
    tampered = approve("start_flow").model_copy(update={"resource_id": OTHER_FLOW_ARN})
    assert_rejected(FailureKind.APPROVAL_REQUIRED, "start", tampered)


def test_start_flow_rejects_approval_for_another_action():
    assert_rejected(FailureKind.APPROVAL_REQUIRED, "start", approve("stop_flow"))


def test_start_flow_rejects_expired_approval():
    assert_rejected(
        FailureKind.APPROVAL_EXPIRED,
        "start",
        approve("start_flow", expires_at=NOW),
    )


def test_start_flow_rejects_bad_signature():
    assert_rejected(
        FailureKind.APPROVAL_REQUIRED,
        "start",
        approve("start_flow", signing_key=OTHER_KEY),
    )


def test_start_flow_returns_verified_before_and_after_states(tmp_path):
    client = replay_write(tmp_path, "start", "STANDBY", "ACTIVE")

    result = start_flow(approve("start_flow"), client, KEY, NOW)

    assert result.before.state is FlowState.STANDBY
    assert result.after.state is FlowState.ACTIVE
    assert result.verified is True
    assert ("start_flow", {"FlowArn": FLOW_ARN}) in client.calls


def test_start_flow_returns_unverified_last_observation_after_deadline(tmp_path):
    client = replay_write(tmp_path, "start", "STANDBY", "STANDBY")
    no_wait = FlowPoller(
        timeout_seconds=0,
        interval_seconds=0,
        monotonic=lambda: 0,
        sleep=lambda _seconds: None,
    )

    result = start_flow(approve("start_flow"), client, KEY, NOW, no_wait)

    assert result.before.state is FlowState.STANDBY
    assert result.after.state is FlowState.STANDBY
    assert result.verified is False
    assert ("start_flow", {"FlowArn": FLOW_ARN}) in client.calls


@pytest.mark.parametrize(
    ("write", "action", "state"),
    [(start_flow, "start", "ACTIVE"), (stop_flow, "stop", "STANDBY")],
)
def test_a_flow_already_in_the_target_state_is_a_verified_no_op(tmp_path, write, action, state):
    """T62: idempotent means MediaConnect isn't called when there's nothing to do."""
    client = replay_write(tmp_path, action, state, state)

    result = write(approve(f"{action}_flow"), client, KEY, NOW)

    assert (result.before.state, result.after.state, result.verified) == (
        FlowState(state),
        FlowState(state),
        True,
    )
    assert [call for call, _ in client.calls] == ["describe_flow", "describe_flow"]
