"""One request: a new question, or the operator's decision on a paused write.

The agent runs on a worker thread; each StreamEvent is yielded as its hook records it, so
a client sees task_started and tool_called while tools and the model are still working.
"""

import queue
import threading
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

from strands import Agent
from strands.agent.agent_result import AgentResult
from strands.tools.executors import SequentialToolExecutor

from agentic_iops_streaming.bootstrap.create_agentic_iops import AgenticIops
from agentic_iops_streaming.bootstrap.create_session_manager import create_session_manager
from agentic_iops_streaming.domain.agentic_iops_request import AgenticIopsRequest
from agentic_iops_streaming.domain.pending_approval import read_pending_approvals
from agentic_iops_streaming.workflows.approve_write_calls import ApproveWriteCalls
from agentic_iops_streaming.workflows.limit_tool_calls import ToolCallBudget
from agentic_iops_streaming.workflows.record_stream_events import StreamEventRecorder
from media_ops_contracts.stream_event import StreamEvent
from media_ops_contracts.tool_failure import FailureKind, ToolFailure

_TURN_ENDED = object()


def stream_agentic_iops_turn(
    iops: AgenticIops,
    request: AgenticIopsRequest,
    *,
    session_id: str,
    actor_id: str,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    record_result: Callable[[AgentResult], None] = lambda result: None,
    record_skill: Callable[[str], None] = lambda skill: None,
) -> Iterator[StreamEvent]:
    """Yield the turn's events as they happen; re-raise the worker's exception, if any."""
    events: queue.Queue = queue.Queue()

    def run() -> None:
        try:
            run_agentic_iops_turn(
                iops,
                request,
                session_id,
                actor_id,
                clock,
                publish=events.put,
                record_result=record_result,
                record_skill=record_skill,
            )
        except Exception as error:  # handed to the consuming thread, which re-raises
            events.put(error)
        finally:
            events.put(_TURN_ENDED)

    threading.Thread(target=run, name=f"agentic-iops-turn-{session_id}", daemon=True).start()
    while (item := events.get()) is not _TURN_ENDED:
        if isinstance(item, Exception):
            raise item
        yield item


def run_agentic_iops_turn(
    iops: AgenticIops,
    request: AgenticIopsRequest,
    session_id: str,
    actor_id: str,
    clock: Callable[[], datetime],
    *,
    publish: Callable[[StreamEvent], None],
    record_result: Callable[[AgentResult], None] = lambda result: None,
    record_skill: Callable[[str], None] = lambda skill: None,
) -> None:
    recorder = StreamEventRecorder(
        iops.surface,
        session_id=session_id,
        actor_id=actor_id,
        publish=publish,
        record_skill=record_skill,
    )
    budget = ToolCallBudget(iops.settings.agentic_iops_tool_budget)
    approvals = ApproveWriteCalls(
        iops.surface.writes,
        actor_id=actor_id,
        signing_key=iops.signing_key,
        recorder=recorder,
        clock=clock,
    )
    agent = Agent(
        model=iops.model,
        tools=iops.tools,
        system_prompt=iops.system_prompt,
        hooks=[budget, recorder, approvals],  # in this order: budget first
        session_manager=create_session_manager(iops.settings, session_id, actor_id),
        tool_executor=SequentialToolExecutor(),
        callback_handler=None,
    )
    agent_input = choose_agent_input(agent, request, actor_id)
    if isinstance(agent_input, ToolFailure):
        recorder.fail(agent_input)
        return
    result = agent(agent_input)
    record_result(result)
    report_turn_usage(recorder, result, iops.settings.agent_model_id)
    if recorder.has_deferred_terminal:
        recorder.flush_terminal()
    elif budget.exceeded:
        recorder.fail(budget.exceeded)
    elif result.stop_reason != "interrupt":
        recorder.answer(str(result).strip())


def report_turn_usage(recorder: StreamEventRecorder, result: Any, model_id: str | None) -> None:
    """Report model-backed usage before the turn's final terminal event."""
    if model_id is None:
        return
    usage = result.metrics.accumulated_usage
    recorder.usage(
        model_id,
        input_tokens=usage.get("inputTokens", 0),
        output_tokens=usage.get("outputTokens", 0),
        total_tokens=usage.get("totalTokens", 0),
        cache_read_input_tokens=usage.get("cacheReadInputTokens", 0),
        cache_write_input_tokens=usage.get("cacheWriteInputTokens", 0),
    )


def choose_agent_input(agent: Agent, request: AgenticIopsRequest, actor_id: str) -> Any:
    """The prompt, or an interrupt response; a ToolFailure when neither may run."""
    pending = list(read_pending_approvals(agent.state).values())
    decision = request.decision
    if decision is None:
        if pending:
            return ToolFailure(
                FailureKind.INVALID_REQUEST,
                "An action in this session is waiting for the operator's decision.",
                f"Send the decision for approval {pending[0].approval_id} first.",
            )
        return request.prompt
    match = next((p for p in pending if p.approval_id == decision.approval_id), None)
    if match is None or match.proposal.actor_id != actor_id:
        return ToolFailure(
            FailureKind.APPROVAL_REQUIRED,
            "No such approval is pending for this operator in this session.",
            "Check the approval id, or ask for the action again.",
        )
    response = {"approve": decision.approve, "actor_id": actor_id, "reason": decision.reason}
    return [{"interruptResponse": {"interruptId": match.approval_id, "response": response}}]
