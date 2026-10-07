"""Pause every write for the operator, then sign exactly what was approved
(extend_agentic_iops_streaming.md §4).

First call: build the proposal, store it with its deadline in agent.state, and interrupt.
On resume: refuse a rejection, another actor, a late decision or a changed call; otherwise
sign an ApprovedAction with the stored deadline and put it into the tool input.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any

from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry
from strands.interrupt import InterruptException

from agentic_iops_streaming.domain.pending_approval import (
    PendingApproval,
    check_approval_decision,
    read_pending_approvals,
    write_pending_approvals,
)
from agentic_iops_streaming.domain.propose_write_action import propose_write_action
from agentic_iops_streaming.workflows.record_stream_events import StreamEventRecorder
from media_ops_contracts.approved_action import APPROVAL_LIFETIME, sign_approved_action
from media_ops_contracts.domain_pack import WriteTool
from media_ops_contracts.tool_failure import FailureKind, ToolFailure

APPROVAL_INTERRUPT = "approve-write"


class ApproveWriteCalls(HookProvider):
    def __init__(
        self,
        writes: dict[str, WriteTool],
        *,
        actor_id: str,
        signing_key: bytes,
        recorder: StreamEventRecorder,
        clock: Callable[[], datetime],
    ) -> None:
        self.writes = writes
        self.actor_id = actor_id
        self.signing_key = signing_key
        self.recorder = recorder
        self.clock = clock

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self.require_approval)

    def require_approval(self, event: BeforeToolCallEvent) -> None:
        write = self.writes.get(event.tool_use["name"])
        if write is None or event.cancel_tool:
            return
        tool_input = event.tool_use["input"]
        current = propose_write_action(write, tool_input, actor_id=self.actor_id)
        tool_use_id = event.tool_use["toolUseId"]
        pending = read_pending_approvals(event.agent.state)
        stored = pending.get(tool_use_id)
        asked = stored or PendingApproval(
            approval_id="", proposal=current, expires_at=self.clock() + APPROVAL_LIFETIME
        )
        reason = asked.model_dump(mode="json", exclude={"approval_id"})
        try:
            decision = event.interrupt(APPROVAL_INTERRUPT, reason=reason)
        except InterruptException as raised:
            if stored is None:
                stored = asked.model_copy(update={"approval_id": raised.interrupt.id})
                pending[tool_use_id] = stored
                write_pending_approvals(event.agent.state, pending)
                self.recorder.request_approval(stored)
            raise
        pending.pop(tool_use_id, None)
        write_pending_approvals(event.agent.state, pending)
        tool_input.pop("approved_action", None)  # never a value the model supplied
        if stored is None:
            self.refuse(event, self.unknown_approval())
            return
        if not decision.get("approve"):
            event.cancel_tool = "Rejected by the operator."
            return
        failure = check_approval_decision(stored, decision, current, self.clock())
        if failure:
            self.refuse(event, failure)
            return
        approved = sign_approved_action(
            stored.proposal,
            approval_id=stored.approval_id,
            expires_at=stored.expires_at,
            signing_key=self.signing_key,
        )
        tool_input["approved_action"] = approved.model_dump(mode="json")

    def refuse(self, event: BeforeToolCallEvent, failure: ToolFailure) -> None:
        event.cancel_tool = failure.message
        self.recorder.fail(failure)

    def unknown_approval(self) -> ToolFailure:
        return ToolFailure(
            FailureKind.APPROVAL_REQUIRED,
            "This approval is not pending in this session.",
            "Propose the action again.",
        )
