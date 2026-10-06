"""Run one scripted investigation through the real hub, packs and fixtures; print events.

uv run --package media-ops-hub demo-hub    (what `just demo` runs, from the repository root)
"""

import os
import tempfile
from collections.abc import MutableMapping
from pathlib import Path

from strands.models import Model

from media_ops_contracts.stream_event import (
    ErrorEvent,
    FinalAnswer,
    StreamEvent,
    TaskStarted,
    ToolCalled,
)
from media_ops_hub.bootstrap.create_hub import create_hub
from media_ops_hub.demo.scripted_demo_model import ScriptedDemoModel
from media_ops_hub.domain.hub_request import HubRequest
from media_ops_hub.settings.runtime_settings import HubSettings
from media_ops_hub.workflows.run_hub_turn import stream_hub_turn

PROMPT = "Viewers report slate on demo-channel. What is wrong?"
DEMO_ENVIRONMENT = {"DEMO": "1", "ALLOW_WRITES": "false", "DEMO_SCENARIO": "", "MEMORY_ID": ""}


def run_demo(
    environ: MutableMapping[str, str] = os.environ, model: Model | None = None
) -> list[StreamEvent]:
    environ.update(DEMO_ENVIRONMENT)  # replay fixtures; never real AWS, never writes
    with tempfile.TemporaryDirectory(prefix="hub-demo-") as sessions:
        settings = HubSettings(media_domains="medialive", session_dir=Path(sessions))
        hub = create_hub(settings, model=model or ScriptedDemoModel())
        events = []
        for event in stream_hub_turn(
            hub, HubRequest(prompt=PROMPT), session_id="demo", actor_id="demo-operator"
        ):
            print(describe_event(event), flush=True)
            events.append(event)
        return events


def describe_event(event: StreamEvent) -> str:
    if isinstance(event, TaskStarted):
        return f"→ {event.specialist}: started with {event.task}"
    if isinstance(event, ToolCalled):
        target = f" ({event.resource_id})" if event.resource_id else ""
        return f"  tool {event.tool}{target}"
    if isinstance(event, FinalAnswer):
        return f"\n{event.text}"
    if isinstance(event, ErrorEvent):
        return f"! {event.kind}: {event.message} {event.next_action}"
    return f"  {event.type}"


def main() -> None:
    print(f"Scripted model on recorded fixtures (no AWS, no Bedrock).\nOperator: {PROMPT}\n")
    run_demo()


if __name__ == "__main__":
    main()
