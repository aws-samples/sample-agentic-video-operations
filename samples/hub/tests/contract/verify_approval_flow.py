"""Run the hub's happy-path approval contract with a scripted model."""

import tempfile
from pathlib import Path
from typing import Any

from hub_test_setup import build_hub, only, types
from scripted_model import ScriptedModel, call, say


def verify_approval_flow() -> dict[str, Any]:
    """Prove a write pauses, remains inert, then executes once after approval."""
    stop = call("stop_channel", "use-1", channel_id="ch-1")
    with tempfile.TemporaryDirectory(prefix="hub-approval-contract-") as session_dir:
        hub = build_hub(
            Path(session_dir),
            ScriptedModel([stop], [say("Stopped ch-1 and verified IDLE.")]),
        )
        requested = hub.ask("Stop ch-1.")
        approval = only(requested, "approval_requested")

        assert hub.pack.states["ch-1"] == "RUNNING"
        assert hub.pack.approvals == []
        assert types(requested) == ["task_started", "tool_called", "approval_requested"]

        completed = hub.decide(approval.approval_id, approve=True)

        assert types(completed) == [
            "task_started",
            "tool_called",
            "action_completed",
            "verification_completed",
            "final_answer",
        ]
        [signed] = hub.pack.approvals
        assert signed.approval_id == approval.approval_id
        assert signed.expires_at == approval.expires_at
        assert hub.pack.states["ch-1"] == "IDLE"
        assert only(completed, "verification_completed").verified is True
        return {
            "approval_id": approval.approval_id,
            "events": types(requested + completed),
            "writes": len(hub.pack.approvals),
        }


def main() -> None:
    result = verify_approval_flow()
    print(f"approval flow verified: {len(result['events'])} events, {result['writes']} write")


if __name__ == "__main__":
    main()
