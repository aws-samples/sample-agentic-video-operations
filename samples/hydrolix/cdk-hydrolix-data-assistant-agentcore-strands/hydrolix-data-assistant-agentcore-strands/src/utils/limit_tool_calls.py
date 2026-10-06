"""A request's tool budget: at most REQUEST_TOOL_CALL_BUDGET calls, all before its deadline.

The orchestrator and its subagents share one budget, so the limits are per request.
"""

import time
from threading import Lock
from typing import Any

from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry

# Three subagents, each with a table lookup and its two query attempts, plus the
# orchestrator's own calls, fit with room to spare.
REQUEST_TOOL_CALL_BUDGET = 16


class ToolCallBudget(HookProvider):
    """One per request, registered on every agent that request builds."""

    def __init__(self, deadline: float, limit: int = REQUEST_TOOL_CALL_BUDGET) -> None:
        self.deadline = deadline  # time.monotonic() seconds
        self.limit = limit
        self.calls = 0
        self._lock = Lock()  # subagents may run tools at the same time

    @property
    def spent(self) -> bool:
        return self.calls > self.limit

    @property
    def spent_message(self) -> str:
        return (
            f"This request reached its budget of {self.limit} tool calls. "
            "Answer with the data you already have."
        )

    def seconds_left(self) -> float:
        return self.deadline - time.monotonic()

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self.count_call)

    def count_call(self, event: BeforeToolCallEvent) -> None:
        with self._lock:
            self.calls += 1
            within = self.calls <= self.limit
        if within and self.seconds_left() > 0:
            return
        event.cancel_tool = (
            self.spent_message
            if not within
            else "This request is out of time. Answer with the data you already have."
        )
        event.invocation_state.setdefault("request_state", {})["stop_event_loop"] = True
