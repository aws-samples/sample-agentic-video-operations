"""The two workflow reads, both from our store and never from AWS (§8.1, §8.4).

A monitoring turn loads a stored chain with `get_workflow`; `list_workflows(contains_arn=...)`
is how one channel or flow finds the workflow it belongs to.
"""

from agentic_iops_streaming.domain.workflow_records import Workflow, WorkflowSummary
from agentic_iops_streaming.domain.workflow_store import (
    WorkflowStore,
    require_workflow_id,
    unknown_workflow_failure,
)


def list_workflows(store: WorkflowStore, contains_arn: str | None = None) -> list[WorkflowSummary]:
    """One summary per workflow, at its highest version, sorted by name then id."""
    return store.summaries(contains_arn)


def get_workflow(store: WorkflowStore, workflow_id: str, version: int | None = None) -> Workflow:
    """One stored version, or the latest; an unknown workflow is RESOURCE_NOT_FOUND."""
    workflow = store.read(require_workflow_id(workflow_id), version)
    if workflow is None:
        raise unknown_workflow_failure(workflow_id, version)
    return workflow
