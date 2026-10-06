"""Deterministic Strands model driven by scenario.yaml turns."""

import json
from collections.abc import AsyncIterator
from typing import Any

from scenario_models import ModelBlock
from strands.models import Model


class ScriptedEvalModel(Model):
    def __init__(self, turns: list[list[ModelBlock]]) -> None:
        self.turns = list(turns)
        self.requested_calls: list[ModelBlock] = []

    def update_config(self, **model_config: Any) -> None:
        pass

    def get_config(self) -> dict[str, Any]:
        return {}

    def structured_output(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def stream(
        self, messages: Any, tool_specs: Any = None, *args: Any, **kwargs: Any
    ) -> AsyncIterator[Any]:
        blocks = self.turns.pop(0) if self.turns else [ModelBlock(answer="No scripted turn.")]
        yield {"messageStart": {"role": "assistant"}}
        for index, block in enumerate(blocks):
            if block.tool:
                self.requested_calls.append(block)
                tool_use_id = f"eval-{len(self.requested_calls)}-{index}"
                yield {
                    "contentBlockStart": {
                        "start": {"toolUse": {"name": block.tool, "toolUseId": tool_use_id}}
                    }
                }
                yield {
                    "contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(block.input)}}}
                }
            else:
                yield {"contentBlockDelta": {"delta": {"text": block.answer or ""}}}
            yield {"contentBlockStop": {}}
        stop = "tool_use" if any(block.tool for block in blocks) else "end_turn"
        yield {"messageStop": {"stopReason": stop}}
        yield {
            "metadata": {
                "usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
                "metrics": {"latencyMs": 1},
            }
        }
