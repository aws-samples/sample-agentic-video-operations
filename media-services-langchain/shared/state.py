"""Shared state schemas for LangGraph agents."""

from typing import TypedDict, Annotated, Literal, Optional
from langgraph.graph import MessagesState
from operator import add


class TodoItem(TypedDict):
    """A single task in the coordinator's execution plan (write_todos pattern)."""
    task_id: str
    description: str
    target_agent: Literal["eml", "emx"]
    priority: int
    depends_on: list[str]
    status: Literal["pending", "in_progress", "completed", "failed"]
    result: Optional[str]


class CoordinatorState(MessagesState):
    """State for the coordinator graph."""
    classification: dict
    todos: Annotated[list[TodoItem], add]
    requires_approval: bool
    approval_status: Literal["pending", "approved", "rejected", "not_required"]
    agent_results: Annotated[list[dict], add]
    session_id: str
    trace_id: str


class SpecialistState(MessagesState):
    """State for EML/EMX specialist graphs."""
    task: dict
    session_id: str
    actor_id: str
