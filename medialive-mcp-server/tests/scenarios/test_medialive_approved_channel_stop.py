"""An approved stop runs once, then verifies the channel reaches IDLE (tool-contract §3)."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from medialive_mcp.adapters.media_live.stop_channel import stop_channel
from medialive_mcp.domain.write_requirements import ApprovalCheck, VerificationPolicy

from media_ops_contracts.approved_action import ActionProposal, sign_approved_action
from media_ops_contracts.replay_fixture_client import ReplayFixtureClient
from media_ops_contracts.tool_failure import FailureKind, ToolFailure

KEY = b"scenario-key"
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
FAST = VerificationPolicy(deadline_seconds=10, interval_seconds=1, sleep=lambda _: None)


@pytest.fixture
def medialive(tmp_path):
    scenario = tmp_path / "stop"
    scenario.mkdir()
    states = [{"Id": "1234567", "Name": "demo", "State": state} for state in
              ("RUNNING", "STOPPING", "IDLE")]  # fmt: skip
    (scenario / "medialive.describe_channel.json").write_text(json.dumps({"sequence": states}))
    (scenario / "medialive.stop_channel.json").write_text("{}")
    return ReplayFixtureClient("medialive", scenario="stop", fixtures_dir=tmp_path)


def approval(resource_id="1234567", key=KEY):
    proposal = ActionProposal(actor_id="op", action="stop_channel", resource_id=resource_id)
    return sign_approved_action(
        proposal, approval_id="ap-1", expires_at=NOW + timedelta(minutes=10), signing_key=key
    )


def test_approved_stop_is_sent_once_and_verified_idle(medialive):
    result = stop_channel(medialive, approval(), ApprovalCheck(KEY, NOW), FAST)
    assert (result.before_state, result.after_state, result.verified) == ("RUNNING", "IDLE", True)
    assert [call for call, _ in medialive.calls].count("stop_channel") == 1


def test_stop_with_an_approval_signed_by_another_key_never_reaches_aws(medialive):
    with pytest.raises(ToolFailure) as failure:
        stop_channel(medialive, approval(key=b"forged"), ApprovalCheck(KEY, NOW), FAST)
    assert failure.value.kind is FailureKind.APPROVAL_REQUIRED
    assert medialive.calls == []


def test_stop_reports_unverified_when_the_channel_never_reaches_idle(tmp_path):
    scenario = tmp_path / "stuck"
    scenario.mkdir()
    stuck = {"Id": "1234567", "Name": "demo", "State": "STOPPING"}
    (scenario / "medialive.describe_channel.json").write_text(json.dumps(stuck))
    (scenario / "medialive.stop_channel.json").write_text("{}")
    medialive = ReplayFixtureClient("medialive", scenario="stuck", fixtures_dir=tmp_path)
    clock = iter(range(100))
    policy = VerificationPolicy(
        deadline_seconds=3, sleep=lambda _: None, monotonic=lambda: next(clock)
    )
    result = stop_channel(medialive, approval(), ApprovalCheck(KEY, NOW), policy)
    assert (result.after_state, result.verified) == ("STOPPING", False)
