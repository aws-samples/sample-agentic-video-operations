"""Typed events every agent runtime streams (extend_the_hub.md §1).

Same discriminated-union pattern as sample-agentic-platform's streaming_models.py:
parse any event with `STREAM_EVENT_ADAPTER.validate_json(line)`.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, Field, TypeAdapter

from media_ops_contracts.approved_action import ActionProposal
from media_ops_contracts.tool_failure import FailureKind


class StreamEventType(StrEnum):
    TASK_STARTED = "task_started"
    TOOL_CALLED = "tool_called"
    APPROVAL_REQUESTED = "approval_requested"
    ACTION_COMPLETED = "action_completed"
    VERIFICATION_COMPLETED = "verification_completed"
    FINAL_ANSWER = "final_answer"
    ERROR = "error"


class BaseStreamEvent(BaseModel):
    session_id: str
    at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))


class TaskStarted(BaseStreamEvent):
    type: Literal[StreamEventType.TASK_STARTED] = StreamEventType.TASK_STARTED
    specialist: str
    task: str


class ToolCalled(BaseStreamEvent):
    """A tool call; raw tool output is never streamed."""

    type: Literal[StreamEventType.TOOL_CALLED] = StreamEventType.TOOL_CALLED
    tool: str
    read_only: bool
    resource_id: str | None = None


class ApprovalRequested(BaseStreamEvent):
    type: Literal[StreamEventType.APPROVAL_REQUESTED] = StreamEventType.APPROVAL_REQUESTED
    approval_id: str
    proposal: ActionProposal
    risk: Literal["low", "high"]
    expires_at: AwareDatetime


class ActionCompleted(BaseStreamEvent):
    type: Literal[StreamEventType.ACTION_COMPLETED] = StreamEventType.ACTION_COMPLETED
    approval_id: str
    action: str
    resource_id: str


class VerificationCompleted(BaseStreamEvent):
    type: Literal[StreamEventType.VERIFICATION_COMPLETED] = StreamEventType.VERIFICATION_COMPLETED
    approval_id: str
    verified: bool
    before_state: str
    after_state: str


class FinalAnswer(BaseStreamEvent):
    type: Literal[StreamEventType.FINAL_ANSWER] = StreamEventType.FINAL_ANSWER
    text: str


class ErrorEvent(BaseStreamEvent):
    type: Literal[StreamEventType.ERROR] = StreamEventType.ERROR
    kind: FailureKind
    message: str
    next_action: str


StreamEvent = Annotated[
    TaskStarted
    | ToolCalled
    | ApprovalRequested
    | ActionCompleted
    | VerificationCompleted
    | FinalAnswer
    | ErrorEvent,
    Field(discriminator="type"),
]

STREAM_EVENT_ADAPTER: TypeAdapter[StreamEvent] = TypeAdapter(StreamEvent)


def encode_stream_event(event: StreamEvent) -> str:
    """Serialize one StreamEvent exactly once, for SSE or AgentCore streaming.

    Validating through the union rejects anything that is not one of its members,
    such as a bare BaseStreamEvent, before it reaches a client.
    """
    validated = STREAM_EVENT_ADAPTER.validate_python(event)
    return STREAM_EVENT_ADAPTER.dump_json(validated).decode()
