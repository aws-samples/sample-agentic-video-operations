"""Collect the StreamEvents of one turn and log each one (extend_agentic_iops_streaming.md §1, §6).

Raw tool output never becomes an event: a tool call is reported by name and kind only,
and a write by the ActionResult fields.
"""

import json
import logging
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError
from strands.hooks import AfterToolCallEvent, BeforeToolCallEvent, HookProvider, HookRegistry

from agentic_iops_streaming.bootstrap.wrap_pack_tools import ToolSurface
from agentic_iops_streaming.domain.pending_approval import PendingApproval
from agentic_iops_streaming.prompts.build_system_prompt import PROMPT_VERSION
from media_ops_contracts.action_result import ActionResult
from media_ops_contracts.estimate_model_cost import estimate_model_cost_usd
from media_ops_contracts.stream_event import (
    ActionCompleted,
    ApprovalRequested,
    ErrorEvent,
    FinalAnswer,
    StreamEvent,
    TaskStarted,
    ToolCalled,
    UsageReported,
    VerificationCompleted,
)
from media_ops_contracts.tool_failure import ToolFailure

LOGGER = logging.getLogger("agentic_iops_streaming")


class StreamEventRecorder(HookProvider):
    def __init__(
        self,
        surface: ToolSurface,
        *,
        session_id: str,
        actor_id: str,
        publish: Callable[[StreamEvent], None] = lambda event: None,
        record_skill: Callable[[str], None] = lambda skill: None,
    ) -> None:
        self.surface = surface
        self.session_id = session_id
        self.actor_id = actor_id
        self.publish = publish  # called as each event is recorded, so callers can stream it
        self.record_skill = record_skill
        self.events: list[StreamEvent] = []
        self._started_packs: set[str] = set()
        self._deferred_terminal: ApprovalRequested | None = None

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self.record_tool_call)
        registry.add_callback(AfterToolCallEvent, self.record_write_result)

    def record_tool_call(self, event: BeforeToolCallEvent) -> None:
        if event.cancel_tool:
            return
        name = event.tool_use["name"]
        pack = self.surface.pack_by_tool.get(name)
        if pack and pack not in self._started_packs:
            self._started_packs.add(pack)
            self.add(TaskStarted(session_id=self.session_id, specialist=pack, task=name))
        write = self.surface.writes.get(name)
        resource = event.tool_use["input"].get(write.resource_parameter) if write else None
        skill = event.tool_use["input"].get("name") if name == "load_skill" else None
        if skill:
            self.record_skill(str(skill))
        self.add(
            ToolCalled(
                session_id=self.session_id,
                tool=name,
                read_only=write is None,
                resource_id=None if resource is None else str(resource),
            ),
            skill_name=skill,
        )

    def record_write_result(self, event: AfterToolCallEvent) -> None:
        if event.tool_use["name"] not in self.surface.writes:
            return
        if event.cancel_message or event.result.get("status") != "success":
            return
        try:
            result = ActionResult.model_validate_json(event.result["content"][0]["text"])
        except (KeyError, IndexError, ValidationError):
            return
        self.add(
            ActionCompleted(
                session_id=self.session_id,
                approval_id=result.approval_id,
                action=result.action,
                resource_id=result.resource_id,
            )
        )
        self.add(
            VerificationCompleted(
                session_id=self.session_id,
                approval_id=result.approval_id,
                verified=result.verified,
                before_state=result.before_state,
                after_state=result.after_state,
            )
        )

    def request_approval(self, pending: PendingApproval) -> None:
        self.defer_terminal(
            ApprovalRequested(
                session_id=self.session_id,
                approval_id=pending.approval_id,
                proposal=pending.proposal,
                risk="high",
                expires_at=pending.expires_at,
            )
        )

    @property
    def has_deferred_terminal(self) -> bool:
        return self._deferred_terminal is not None

    def defer_terminal(self, event: ApprovalRequested) -> None:
        if self._deferred_terminal is not None:
            raise RuntimeError("Only one terminal event may be deferred per turn.")
        self._deferred_terminal = event

    def flush_terminal(self) -> None:
        event, self._deferred_terminal = self._deferred_terminal, None
        if event is not None:
            self.add(event)

    def fail(self, failure: ToolFailure) -> None:
        self.add(self.failure_event(failure))

    def failure_event(self, failure: ToolFailure) -> ErrorEvent:
        return ErrorEvent(
            session_id=self.session_id,
            kind=failure.kind,
            message=failure.message,
            next_action=failure.next_action,
        )

    def answer(self, text: str) -> None:
        self.add(FinalAnswer(session_id=self.session_id, text=text))

    def usage(
        self,
        model_id: str,
        *,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        cache_read_input_tokens: int,
        cache_write_input_tokens: int,
    ) -> None:
        self.add(
            UsageReported(
                session_id=self.session_id,
                model_id=model_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                cache_read_input_tokens=cache_read_input_tokens,
                cache_write_input_tokens=cache_write_input_tokens,
                estimated_usd=estimate_model_cost_usd(model_id, input_tokens, output_tokens),
            )
        )

    def add(self, event: StreamEvent, *, skill_name: str | None = None) -> None:
        self.events.append(event)
        LOGGER.info(json.dumps(self.log_fields(event, skill_name)))
        self.publish(event)

    def log_fields(self, event: StreamEvent, skill_name: str | None) -> dict[str, Any]:
        """Ids and names only: no prompt, tool output or answer text."""
        tool = getattr(event, "tool", None) or getattr(event, "action", None)
        fields = {
            "event": event.type,
            "session.id": self.session_id,
            "actor.id": self.actor_id,
            "prompt.version": PROMPT_VERSION,
            "pack.name": getattr(event, "specialist", None) or self.surface.pack_by_tool.get(tool),
            "tool.name": tool,
            "skill.name": skill_name,
            "approval.id": getattr(event, "approval_id", None),
            "model.id": getattr(event, "model_id", None),
            "tokens.input": getattr(event, "input_tokens", None),
            "tokens.output": getattr(event, "output_tokens", None),
            "tokens.cache_read_input": getattr(event, "cache_read_input_tokens", None),
            "tokens.cache_write_input": getattr(event, "cache_write_input_tokens", None),
            "cost.estimated_usd": getattr(event, "estimated_usd", None),
        }
        return {key: value for key, value in fields.items() if value is not None}
