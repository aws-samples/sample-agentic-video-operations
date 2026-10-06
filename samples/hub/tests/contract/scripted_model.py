"""A Strands model that replays scripted assistant turns: offline, deterministic tests."""

import asyncio
import json
import threading
from collections.abc import AsyncIterator
from typing import Any

from strands.models import Model


def call(tool_name: str, tool_use_id: str, /, **tool_input: Any) -> dict[str, Any]:
    return {"toolUse": {"name": tool_name, "toolUseId": tool_use_id, "input": tool_input}}


def say(text: str) -> dict[str, Any]:
    return {"text": text}


class ScriptedModel(Model):
    """Each model call replays the next turn: a list of `call(...)` and `say(...)` blocks."""

    def __init__(self, *turns: list[dict[str, Any]]) -> None:
        self.turns = list(turns)
        self.tool_names: list[str] = []
        self.messages: list[Any] = []

    def update_config(self, **model_config: Any) -> None:
        pass

    def get_config(self) -> dict[str, Any]:
        return {}

    def structured_output(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def stream(
        self, messages: Any, tool_specs: Any = None, *args: Any, **kwargs: Any
    ) -> AsyncIterator[Any]:
        self.tool_names = [spec["name"] for spec in tool_specs or []]
        self.messages = list(messages)
        blocks = self.turns.pop(0) if self.turns else [say("No more scripted turns.")]
        yield {"messageStart": {"role": "assistant"}}
        for block in blocks:
            if "toolUse" in block:
                use = block["toolUse"]
                start = {"toolUse": {"name": use["name"], "toolUseId": use["toolUseId"]}}
                yield {"contentBlockStart": {"start": start}}
                yield {
                    "contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(use["input"])}}}
                }
            else:
                yield {"contentBlockDelta": {"delta": {"text": block["text"]}}}
            yield {"contentBlockStop": {}}
        stop = "tool_use" if any("toolUse" in block for block in blocks) else "end_turn"
        yield {"messageStop": {"stopReason": stop}}
        usage = {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2}
        yield {"metadata": {"usage": usage, "metrics": {"latencyMs": 1}}}


def last_tool_result(model: ScriptedModel) -> dict[str, Any]:
    """The tool result the model saw on its latest call."""
    blocks = [b for message in model.messages for b in message["content"] if "toolResult" in b]
    return blocks[-1]["toolResult"]


class GatedModel(ScriptedModel):
    """A ScriptedModel whose call number `gate_at` waits until the test opens the gate."""

    def __init__(self, *turns: list[dict[str, Any]], gate_at: int) -> None:
        super().__init__(*turns)
        self.gate_at = gate_at
        self.calls = 0
        self.waiting = threading.Event()
        self.gate = threading.Event()
        self.opened_by_test = False  # False when the 5 s safety timeout released the gate

    async def stream(
        self, messages: Any, tool_specs: Any = None, *args: Any, **kwargs: Any
    ) -> AsyncIterator[Any]:
        self.calls += 1
        if self.calls == self.gate_at:
            self.waiting.set()
            self.opened_by_test = await asyncio.to_thread(self.gate.wait, 5)
        async for event in super().stream(messages, tool_specs, *args, **kwargs):
            yield event
