"""A Strands model that replays one fixed investigation, so the demo needs no Bedrock.

The tool calls are real: they run the medialive pack against fixtures/input_loss. Only
the model's choices and its final wording are scripted.
"""

import json
from collections.abc import AsyncIterator
from typing import Any

from strands.models import Model

CHANNEL_ID = "1234567"

DEMO_TURNS: list[list[dict[str, Any]]] = [
    [{"toolUse": {"name": "list_channels", "toolUseId": "demo-1", "input": {}}}],
    [{"toolUse": {"name": "load_skill", "toolUseId": "demo-2", "input": {"name": "diagnose-input-loss"}}}],  # noqa: E501
    [{"toolUse": {"name": "check_channel_issues", "toolUseId": "demo-3", "input": {"channel_id": CHANNEL_ID, "hours_back": 1}}}],  # noqa: E501
    [{"toolUse": {"name": "read_channel_logs", "toolUseId": "demo-4", "input": {"channel_id": CHANNEL_ID}}}],  # noqa: E501
    [{"text": (
        "Impact: viewers of demo-channel on pipeline 0 see slate; pipeline 1 is healthy.\n"
        "Evidence: check_channel_issues reports InputLossSeconds on pipeline 0, still failing, "
        "with an active alert; the channel log says \"no SRT packets received\" on input "
        "demo-primary-srt.\n"
        "Next action: the fault is upstream of MediaLive. Check the SRT sender or the "
        "MediaConnect flow feeding demo-primary-srt; switching inputs needs ALLOW_WRITES "
        "and your approval."
    )}],
]  # fmt: skip


class ScriptedDemoModel(Model):
    def __init__(self, turns: list[list[dict[str, Any]]] | None = None) -> None:
        self.turns = list(turns if turns is not None else DEMO_TURNS)

    def update_config(self, **model_config: Any) -> None:
        pass

    def get_config(self) -> dict[str, Any]:
        return {"model_id": "scripted-demo"}

    def structured_output(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("The scripted demo model has no structured output.")

    async def stream(
        self, messages: Any, tool_specs: Any = None, *args: Any, **kwargs: Any
    ) -> AsyncIterator[Any]:  # noqa: E501
        blocks: list[dict[str, Any]] = (
            self.turns.pop(0) if self.turns else [{"text": "The demo script has ended."}]
        )
        yield {"messageStart": {"role": "assistant"}}
        for block in blocks:
            if "toolUse" in block:
                use = block["toolUse"]
                start = {"toolUse": {"name": use["name"], "toolUseId": use["toolUseId"]}}
                yield {"contentBlockStart": {"start": start}}
                yield {
                    "contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(use["input"])}}}
                }  # noqa: E501
            else:
                yield {"contentBlockDelta": {"delta": {"text": block["text"]}}}
            yield {"contentBlockStop": {}}
        stop = "tool_use" if any("toolUse" in block for block in blocks) else "end_turn"
        yield {"messageStop": {"stopReason": stop}}
        yield {
            "metadata": {
                "usage": {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0},
                "metrics": {"latencyMs": 0},
            }
        }  # noqa: E501
