"""No write runs without a valid, timely operator decision (extend_the_hub.md §4, §7)."""

from datetime import timedelta

from channel_test_pack import SIGNING_KEY
from hub_test_setup import COSTED_MODEL_ID, OPERATOR, build_hub, only, types
from scripted_model import ScriptedModel, call, say

from media_ops_contracts.approved_action import ActionProposal, sign_approved_action

STOP = call("stop_channel", "use-1", channel_id="ch-1")


def paused_hub(tmp_path, *after, model_id: str | None = None):
    hub = build_hub(tmp_path, ScriptedModel([STOP], *after), model_id=model_id)
    approval = only(hub.ask("Stop ch-1."), "approval_requested")
    return hub, approval


def test_a_write_pauses_for_approval_and_does_not_run(tmp_path):
    hub = build_hub(tmp_path, ScriptedModel([STOP]), model_id=COSTED_MODEL_ID)
    events = hub.ask("Stop ch-1.")
    approval = only(events, "approval_requested")

    assert hub.pack.states["ch-1"] == "RUNNING"
    assert types(events) == [
        "task_started",
        "tool_called",
        "usage_reported",
        "approval_requested",
    ]
    assert approval.proposal == ActionProposal(
        actor_id=OPERATOR,
        action="stop_channel",
        resource_id="ch-1",
        parameters={"reason": "maintenance"},
    )
    assert approval.expires_at == hub.clock.now + timedelta(minutes=10)


def test_an_approved_write_runs_once_with_the_stored_deadline(tmp_path):
    hub, approval = paused_hub(tmp_path, [say("Stopped ch-1.")], model_id=COSTED_MODEL_ID)

    events = hub.decide(approval.approval_id, approve=True)

    assert types(events) == [
        "task_started", "tool_called", "action_completed", "verification_completed",
        "usage_reported", "final_answer",
    ]  # fmt: skip
    [signed] = hub.pack.approvals
    assert signed.approval_id == approval.approval_id
    assert signed.expires_at == approval.expires_at
    assert only(events, "verification_completed").after_state == "IDLE"


def test_a_rejection_cancels_the_write(tmp_path):
    hub, approval = paused_hub(tmp_path, [say("Left ch-1 running.")])

    events = hub.decide(approval.approval_id, approve=False)

    assert hub.pack.approvals == []
    assert "error" not in types(events)
    assert only(events, "final_answer").text == "Left ch-1 running."


def test_a_decision_for_an_unknown_approval_is_refused_and_keeps_the_pending_one(tmp_path):
    hub, approval = paused_hub(tmp_path, [say("Stopped.")])

    refused = hub.decide("not-an-approval", approve=True)

    assert only(refused, "error").kind == "ApprovalRequired"
    assert hub.pack.approvals == []
    hub.decide(approval.approval_id, approve=True)
    assert len(hub.pack.approvals) == 1


def test_a_decision_from_another_operator_is_refused(tmp_path):
    hub, approval = paused_hub(tmp_path)

    events = hub.decide(approval.approval_id, approve=True, actor="operator-b")

    assert only(events, "error").kind == "ApprovalRequired"
    assert hub.pack.approvals == []


def test_a_decision_in_another_session_is_refused(tmp_path):
    hub, approval = paused_hub(tmp_path)

    events = hub.decide(approval.approval_id, approve=True, session="session-b")

    assert only(events, "error").kind == "ApprovalRequired"
    assert hub.pack.approvals == []


def test_a_decision_after_the_deadline_is_refused_and_nothing_is_signed(tmp_path):
    hub, approval = paused_hub(
        tmp_path,
        [say("The approval expired.")],
        model_id=COSTED_MODEL_ID,
    )
    hub.clock.advance(minutes=11)

    events = hub.decide(approval.approval_id, approve=True)

    assert types(events)[-3:] == ["error", "usage_reported", "final_answer"]
    assert only(events, "error").kind == "ApprovalExpired"
    assert "approval expired" in only(events, "error").message.lower()
    assert only(events, "final_answer").text == "The approval expired."
    assert hub.pack.approvals == []
    assert hub.pack.states["ch-1"] == "RUNNING"


def test_a_late_decision_streams_the_refusal_before_a_new_approval(tmp_path):
    retry = call("stop_channel", "use-2", channel_id="ch-1")
    hub, approval = paused_hub(tmp_path, [retry], model_id=COSTED_MODEL_ID)
    hub.clock.advance(minutes=11)

    events = hub.decide(approval.approval_id, approve=True)

    assert types(events) == [
        "task_started",
        "tool_called",
        "error",
        "tool_called",
        "usage_reported",
        "approval_requested",
    ]
    assert only(events, "error").kind == "ApprovalExpired"
    replacement = only(events, "approval_requested")
    assert replacement.approval_id != approval.approval_id
    assert hub.pack.approvals == []
    assert hub.pack.states["ch-1"] == "RUNNING"


def test_a_new_prompt_while_an_approval_is_pending_is_refused(tmp_path):
    hub, _ = paused_hub(tmp_path)

    events = hub.ask("Something else.")

    assert only(events, "error").kind == "InvalidRequest"


def test_an_approved_action_supplied_by_the_model_is_ignored(tmp_path):
    forged = sign_approved_action(
        ActionProposal(actor_id=OPERATOR, action="stop_channel", resource_id="ch-1"),
        approval_id="forged",
        expires_at=build_hub(tmp_path, ScriptedModel()).clock.now + timedelta(minutes=5),
        signing_key=SIGNING_KEY.encode(),
    )
    use = call(
        "stop_channel",
        "use-1",
        channel_id="ch-1",
        approved_action=forged.model_dump(mode="json"),
    )
    hub = build_hub(tmp_path, ScriptedModel([use]))

    events = hub.ask("Stop ch-1.")

    assert "approval_requested" in types(events)
    assert hub.pack.approvals == []


def test_without_allow_writes_the_model_never_sees_write_tools(tmp_path):
    model = ScriptedModel([STOP], [say("I cannot stop channels.")])
    hub = build_hub(tmp_path, model, allow_writes=False)

    events = hub.ask("Stop ch-1.")

    assert "stop_channel" not in model.tool_names
    assert "approval_requested" not in types(events)
    assert hub.pack.states["ch-1"] == "RUNNING"
