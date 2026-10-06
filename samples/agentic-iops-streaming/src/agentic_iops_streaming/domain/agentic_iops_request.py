"""What a caller sends the agent (extend_agentic_iops_streaming.md §1)."""

from typing import Self

from pydantic import BaseModel, model_validator


class ApprovalDecision(BaseModel):
    approval_id: str  # the interrupt id streamed in approval_requested
    approve: bool
    reason: str | None = None


class AgenticIopsRequest(BaseModel):
    prompt: str | None = None  # a new question
    decision: ApprovalDecision | None = None  # resumes a paused run

    @model_validator(mode="after")
    def require_prompt_or_decision(self) -> Self:
        if (self.prompt is None) == (self.decision is None):
            raise ValueError("Send exactly one of prompt or decision.")
        return self
