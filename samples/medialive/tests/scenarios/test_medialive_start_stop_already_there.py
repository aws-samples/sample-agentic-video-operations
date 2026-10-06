"""Start and stop idempotency: target and matching transitional states are waiting no-ops."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from media_ops_contracts.approved_action import ActionProposal, sign_approved_action
from media_ops_contracts.replay_fixture_client import ReplayFixtureClient
from medialive_mcp.adapters.media_live.start_channel import start_channel
from medialive_mcp.adapters.media_live.stop_channel import stop_channel
from medialive_mcp.domain.write_requirements import ApprovalCheck, VerificationPolicy

KEY = b"scenario-key"
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
FAST = VerificationPolicy(deadline_seconds=10, interval_seconds=1, sleep=lambda _: None)


def channel_in(tmp_path, state):
    scenario = tmp_path / state.lower()
    scenario.mkdir()
    channel = {"Id": "1234567", "Name": "demo", "State": state}
    (scenario / "medialive.describe_channel.json").write_text(json.dumps(channel))
    # No start_channel/stop_channel fixture: a call would fail the test.
    return ReplayFixtureClient("medialive", scenario=scenario.name, fixtures_dir=tmp_path)


def channel_moving_to(tmp_path, before, after):
    scenario = tmp_path / before.lower()
    scenario.mkdir()
    channels = [{"Id": "1234567", "Name": "demo", "State": state} for state in (before, after)]
    (scenario / "medialive.describe_channel.json").write_text(json.dumps({"sequence": channels}))
    # No start_channel/stop_channel fixture: a call would fail the test.
    return ReplayFixtureClient("medialive", scenario=scenario.name, fixtures_dir=tmp_path)


def approval(action):
    proposal = ActionProposal(actor_id="op", action=action, resource_id="1234567")
    return sign_approved_action(
        proposal, approval_id="ap-1", expires_at=NOW + timedelta(minutes=10), signing_key=KEY
    )


@pytest.mark.parametrize(
    ("write", "action", "state"),
    [(start_channel, "start_channel", "RUNNING"), (stop_channel, "stop_channel", "IDLE")],
)
def test_a_channel_already_in_the_target_state_is_a_verified_no_op(tmp_path, write, action, state):
    medialive = channel_in(tmp_path, state)

    result = write(medialive, approval(action), ApprovalCheck(KEY, NOW), FAST)

    assert (result.before_state, result.after_state, result.verified) == (state, state, True)
    assert [call for call, _ in medialive.calls] == ["describe_channel", "describe_channel"]


@pytest.mark.parametrize(
    ("write", "action", "before", "after"),
    [
        (start_channel, "start_channel", "STARTING", "RUNNING"),
        (stop_channel, "stop_channel", "STOPPING", "IDLE"),
    ],
)
def test_a_channel_already_moving_to_the_target_is_a_verified_waiting_no_op(
    tmp_path, write, action, before, after
):
    medialive = channel_moving_to(tmp_path, before, after)

    result = write(medialive, approval(action), ApprovalCheck(KEY, NOW), FAST)

    assert (result.before_state, result.after_state, result.verified) == (before, after, True)
    assert [call for call, _ in medialive.calls] == ["describe_channel", "describe_channel"]


@pytest.mark.parametrize(
    ("write", "action", "state"),
    [(start_channel, "start_channel", "IDLE"), (stop_channel, "stop_channel", "RUNNING")],
)
def test_a_channel_in_another_state_is_still_sent_the_call(tmp_path, write, action, state):
    scenario = tmp_path / "moving"
    scenario.mkdir()
    target = "RUNNING" if action == "start_channel" else "IDLE"
    states = [{"Id": "1234567", "Name": "demo", "State": s} for s in (state, target)]
    (scenario / "medialive.describe_channel.json").write_text(json.dumps({"sequence": states}))
    (scenario / f"medialive.{action}.json").write_text("{}")
    medialive = ReplayFixtureClient("medialive", scenario="moving", fixtures_dir=tmp_path)

    result = write(medialive, approval(action), ApprovalCheck(KEY, NOW), FAST)

    assert result.verified
    assert [call for call, _ in medialive.calls].count(action) == 1
