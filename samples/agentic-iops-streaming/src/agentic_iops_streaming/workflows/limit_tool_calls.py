"""AGENTIC_IOPS_TOOL_BUDGET: at most N tool calls per request
(extend_agentic_iops_streaming.md §1)."""

from typing import Any

from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry

from media_ops_contracts.tool_failure import FailureKind, ToolFailure


class ToolCallBudget(HookProvider):
    def __init__(self, budget: int) -> None:
        self.budget = budget
        self.calls = 0
        self.exceeded: ToolFailure | None = None

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self.count_call)

    def count_call(self, event: BeforeToolCallEvent) -> None:
        self.calls += 1
        if self.calls <= self.budget:
            return
        self.exceeded = ToolFailure(
            FailureKind.INVALID_REQUEST,
            f"This request reached its budget of {self.budget} tool calls.",
            "Ask a narrower question, naming the channel or flow.",
        )
        event.cancel_tool = self.exceeded.message
        event.invocation_state["request_state"]["stop_event_loop"] = True
