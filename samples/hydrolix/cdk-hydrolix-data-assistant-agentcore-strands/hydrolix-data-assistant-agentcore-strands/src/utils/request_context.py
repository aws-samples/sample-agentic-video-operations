"""
Request Context

Shares one request's values (prompt_uuid, timezone, tool budget and deadline) between the
orchestrator and its subagents. It is a ContextVar, not a process-wide object, so two
requests a runtime serves at once each see their own. Strands runs the subagent tools with
asyncio.to_thread, which copies the context, so a subagent sees the request that called it.
"""

import time
from contextvars import ContextVar
from dataclasses import dataclass, field

from .limit_tool_calls import ToolCallBudget
from .query_record import QueryRecord
from .resolve_user_timezone import DEFAULT_TIMEZONE

# From the moment a request arrives: secret reads, MCP starts and every subagent run.
REQUEST_TIMEOUT_SECONDS = 180


@dataclass(frozen=True)
class RequestContext:
    prompt_uuid: str
    user_timezone: str
    tool_budget: ToolCallBudget  # also holds the request's deadline
    actor_id: str | None = None  # the verified sub (JWT mode); None in IAM mode
    query_records: list[QueryRecord] = field(default_factory=list)  # as they ran


_CURRENT: ContextVar[RequestContext] = ContextVar("hydrolix_request_context")


def set_request_context(
    prompt_uuid: str, user_timezone: str = DEFAULT_TIMEZONE, actor_id: str | None = None
) -> RequestContext:
    """Start a request: its own values, a full tool budget, and a deadline from now."""
    deadline = time.monotonic() + REQUEST_TIMEOUT_SECONDS
    context = RequestContext(prompt_uuid, user_timezone, ToolCallBudget(deadline), actor_id)
    _CURRENT.set(context)
    return context


def get_request_context() -> RequestContext:
    """The current request's context. Outside a request this is an error, not a default."""
    try:
        return _CURRENT.get()
    except LookupError:
        raise RuntimeError("No request context: subagents run only inside a request") from None
