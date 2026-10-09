"""Where a discovered proposal waits for its approval: the session's own state (§8.1).

Discovery happens in one request and the save in a later one, after the operator decides, and
AgentCore may resume that session in another container. So the proposal lives in `agent.state`
with the session, not in this process's memory.
"""

from typing import Any

from agentic_iops_streaming.domain.workflow_records import WorkflowProposal

WORKFLOW_PROPOSALS = "workflow_proposals"  # agent.state key: workflow_id -> WorkflowProposal


def read_workflow_proposals(state: Any) -> dict[str, WorkflowProposal]:
    stored = state.get(WORKFLOW_PROPOSALS) or {}
    return {key: WorkflowProposal.model_validate(value) for key, value in stored.items()}


def write_workflow_proposal(state: Any, proposal: WorkflowProposal) -> None:
    """Keep one proposal per workflow id: a rediscovery replaces the earlier one."""
    held = read_workflow_proposals(state)
    held[proposal.workflow_id] = proposal
    state.set(
        WORKFLOW_PROPOSALS,
        {key: value.model_dump(mode="json") for key, value in held.items()},
    )
