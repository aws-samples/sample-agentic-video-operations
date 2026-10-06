"""Typed input and output records for agentic-iops-streaming eval scenarios."""

from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator


class ModelBlock(BaseModel):
    tool: str | None = None
    input: dict[str, object] = Field(default_factory=dict)
    answer: str | None = None

    @model_validator(mode="after")
    def require_one_block_kind(self) -> Self:
        if (self.tool is None) == (self.answer is None):
            raise ValueError("Each model block needs exactly one of tool or answer.")
        return self


class DecisionStep(BaseModel):
    approval_id: Literal["current", "other"]
    approve: bool
    advance_minutes: int = 0


class ActionVerification(BaseModel):
    action: str
    before_state: str
    after_state: str
    verified: bool = True


class ExpectedResult(BaseModel):
    specialists: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    diagnosis_keywords: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    verifications: list[ActionVerification] = Field(default_factory=list)
    max_tool_calls: int
    writes_attempted: int = 0


class EvalScenario(BaseModel):
    name: str
    prompt: str
    media_domains: list[str]
    fixture: str
    allow_writes: bool = False
    turns: list[list[ModelBlock]]
    decision: DecisionStep | None = None
    expected: ExpectedResult


class EvalResult(BaseModel):
    scenario: str
    passed: bool
    model: str
    input_tokens: int
    output_tokens: int
    tool_calls: list[str]
    skills_loaded: list[str]
    specialists: list[str]
    latency_ms: float
    writes_attempted: int
    verifications: list[ActionVerification]
    failures: list[str]
