"""Run the hub's progressive typed-stream contract with a scripted model."""

import json
import tempfile
from pathlib import Path

from channel_test_pack import RAW_OUTPUT_MARKER
from hub_test_setup import build_hub, types
from scripted_model import GatedModel, call, say

from media_ops_contracts.stream_event import STREAM_EVENT_ADAPTER


def verify_stream_events() -> list[str]:
    """Prove progress arrives before the turn ends and every event validates."""
    describe = call("describe_channel", "use-1", channel_id="ch-1")
    model = GatedModel([describe], [say("ch-1 is RUNNING.")], gate_at=2)
    with tempfile.TemporaryDirectory(prefix="hub-stream-contract-") as session_dir:
        stream = build_hub(Path(session_dir), model).stream("Is ch-1 healthy?")
        events = []
        try:
            events.extend((next(stream), next(stream)))
            assert types(events) == ["task_started", "tool_called"]
            assert model.waiting.wait(5)
            assert not model.gate.is_set()
        finally:
            model.gate.set()
        events.extend(stream)

    payloads = [
        STREAM_EVENT_ADAPTER.dump_python(
            STREAM_EVENT_ADAPTER.validate_python(event),
            mode="json",
        )
        for event in events
    ]
    validated = [STREAM_EVENT_ADAPTER.validate_python(payload).type for payload in payloads]
    assert validated == ["task_started", "tool_called", "final_answer"]
    assert RAW_OUTPUT_MARKER not in json.dumps(payloads)
    assert model.opened_by_test
    return validated


def main() -> None:
    events = verify_stream_events()
    print(f"stream events verified: {', '.join(events)}")


if __name__ == "__main__":
    main()
