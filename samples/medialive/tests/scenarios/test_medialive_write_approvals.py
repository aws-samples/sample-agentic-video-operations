"""Approval-negative coverage for MediaLive stop and immediate input switch writes."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from media_ops_contracts.approved_action import ActionProposal, sign_approved_action
from media_ops_contracts.replay_fixture_client import ReplayFixtureClient
from media_ops_contracts.tool_failure import FailureKind, ToolFailure
from medialive_mcp.adapters.media_live.stop_channel import stop_channel
from medialive_mcp.adapters.media_live.switch_channel_input import switch_channel_input
from medialive_mcp.domain.write_requirements import ApprovalCheck, VerificationPolicy

KEY = b"medialive-test-key"
OTHER_KEY = b"untrusted-key"
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
CHANNEL = "1234567"
OTHER_CHANNEL = "7654321"
SWITCH_PARAMETERS = {
    "action_name": "switch-to-backup",
    "input_attachment": "demo-backup-srt",
}
NO_WAIT = VerificationPolicy(deadline_seconds=0, interval_seconds=0, sleep=lambda _: None)


def approve(
    action,
    *,
    resource_id=CHANNEL,
    parameters=None,
    signing_key=KEY,
    expires_at=NOW + timedelta(minutes=10),
):
    proposal = ActionProposal(
        actor_id="operator-1",
        action=action,
        resource_id=resource_id,
        parameters=parameters or {},
    )
    return sign_approved_action(
        proposal,
        approval_id="approval-1",
        expires_at=expires_at,
        signing_key=signing_key,
    )


def unused_client():
    return ReplayFixtureClient("medialive", scenario="unused", fixtures_dir=Path("fixtures"))


def assert_rejected(write, approved_action, expected_kind):
    client = unused_client()
    with pytest.raises(ToolFailure) as failure:
        write(client, approved_action, ApprovalCheck(KEY, NOW), NO_WAIT)
    assert failure.value.kind is expected_kind
    assert failure.value.next_action
    assert client.calls == []


def test_stop_channel_rejects_missing_approval():
    assert_rejected(stop_channel, None, FailureKind.APPROVAL_REQUIRED)


def test_stop_channel_rejects_resource_changed_after_approval():
    changed = approve("stop_channel").model_copy(update={"resource_id": OTHER_CHANNEL})
    assert_rejected(stop_channel, changed, FailureKind.APPROVAL_REQUIRED)


def test_stop_channel_rejects_approval_for_another_action():
    assert_rejected(
        stop_channel,
        approve("start_channel"),
        FailureKind.APPROVAL_REQUIRED,
    )


def test_stop_channel_rejects_expired_approval():
    assert_rejected(
        stop_channel,
        approve("stop_channel", expires_at=NOW),
        FailureKind.APPROVAL_EXPIRED,
    )


def test_stop_channel_rejects_bad_signature():
    assert_rejected(
        stop_channel,
        approve("stop_channel", signing_key=OTHER_KEY),
        FailureKind.APPROVAL_REQUIRED,
    )


def test_switch_channel_input_rejects_missing_approval():
    assert_rejected(switch_channel_input, None, FailureKind.APPROVAL_REQUIRED)


def test_switch_channel_input_rejects_resource_changed_after_approval():
    changed = approve(
        "switch_channel_input",
        parameters=SWITCH_PARAMETERS,
    ).model_copy(update={"resource_id": OTHER_CHANNEL})
    assert_rejected(switch_channel_input, changed, FailureKind.APPROVAL_REQUIRED)


def test_switch_channel_input_rejects_approval_for_another_action():
    assert_rejected(
        switch_channel_input,
        approve("stop_channel", parameters=SWITCH_PARAMETERS),
        FailureKind.APPROVAL_REQUIRED,
    )


def test_switch_channel_input_rejects_expired_approval():
    assert_rejected(
        switch_channel_input,
        approve("switch_channel_input", parameters=SWITCH_PARAMETERS, expires_at=NOW),
        FailureKind.APPROVAL_EXPIRED,
    )


def test_switch_channel_input_rejects_bad_signature():
    assert_rejected(
        switch_channel_input,
        approve(
            "switch_channel_input",
            parameters=SWITCH_PARAMETERS,
            signing_key=OTHER_KEY,
        ),
        FailureKind.APPROVAL_REQUIRED,
    )


def test_switch_channel_input_uses_replay_and_verifies_both_pipelines(tmp_path):
    scenario = tmp_path / "switch"
    scenario.mkdir()
    states = {
        "sequence": [
            channel_state("demo-primary-srt"),
            channel_state("demo-backup-srt"),
        ]
    }
    (scenario / "medialive.describe_channel.json").write_text(json.dumps(states))
    (scenario / "medialive.batch_update_schedule.json").write_text("{}")
    client = ReplayFixtureClient("medialive", scenario="switch", fixtures_dir=tmp_path)

    result = switch_channel_input(
        client,
        approve("switch_channel_input", parameters=SWITCH_PARAMETERS),
        ApprovalCheck(KEY, NOW),
        NO_WAIT,
    )

    assert result.verified is True
    assert result.before_state == "demo-primary-srt,demo-primary-srt"
    assert result.after_state == "demo-backup-srt,demo-backup-srt"
    [update] = [
        parameters for operation, parameters in client.calls if operation == "batch_update_schedule"
    ]
    [action] = update["Creates"]["ScheduleActions"]
    assert action["ScheduleActionSettings"]["InputSwitchSettings"] == {
        "InputAttachmentNameReference": "demo-backup-srt"
    }


def channel_state(active_input):
    return {
        "Id": CHANNEL,
        "Name": "demo-channel",
        "State": "RUNNING",
        "PipelineDetails": [
            {"PipelineId": "0", "ActiveInputAttachmentName": active_input},
            {"PipelineId": "1", "ActiveInputAttachmentName": active_input},
        ],
    }
