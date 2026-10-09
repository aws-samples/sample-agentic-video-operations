"""The executable contract verifiers stay in the offline Agentic IOPS gate."""

from verify_approval_flow import verify_approval_flow
from verify_stream_events import verify_stream_events


def test_approval_flow_verifier_runs_one_approved_write():
    result = verify_approval_flow()

    assert result["writes"] == 1
    assert result["events"][-3:] == [
        "action_completed",
        "verification_completed",
        "final_answer",
    ]


def test_stream_event_verifier_proves_progressive_typed_delivery():
    assert verify_stream_events() == ["task_started", "tool_called", "final_answer"]
