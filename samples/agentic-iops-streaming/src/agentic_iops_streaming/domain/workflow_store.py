"""The workflow store's port, and the one rule every implementation enforces (§8.4).

Versions are immutable: a save writes `latest + 1` and fails if that version already exists,
so two operators saving the same proposal can't overwrite each other. The store keeps no AWS
or filesystem detail here; `adapters/workflow_store/` holds those.
"""

from typing import Protocol

from agentic_iops_streaming.domain.workflow_records import (
    MAX_WORKFLOW_ID_LENGTH,
    WORKFLOW_ID_FORMAT,
    Workflow,
    WorkflowSummary,
)
from media_ops_contracts.tool_failure import FailureKind, ToolFailure

MAX_ITEM_BYTES = 350_000  # under DynamoDB's 400 KB, with room for attribute names


class VersionAlreadyExists(Exception):
    """Another save took this version first (the condition failed)."""


class WorkflowStore(Protocol):
    """Reads and one conditional write; nothing here reaches AWS for discovery."""

    def save(self, workflow: Workflow) -> Workflow | None:
        """Write this version, or raise VersionAlreadyExists. Return the item read back, or
        None when the read-back found nothing: never the input in its place."""
        ...

    def read(self, workflow_id: str, version: int | None = None) -> Workflow | None:
        """One version, or the latest when `version` is None; None when absent."""
        ...

    def summaries(self, contains_arn: str | None = None) -> list[WorkflowSummary]:
        """One summary per workflow, from its highest version, sorted by name then id.

        With `contains_arn`, only the workflows whose highest version holds that ARN (its
        entry point included), matched in the same pass: no read per workflow.
        """
        ...


def is_workflow_id(workflow_id: str) -> bool:
    return (
        len(workflow_id) <= MAX_WORKFLOW_ID_LENGTH
        and WORKFLOW_ID_FORMAT.fullmatch(workflow_id) is not None
    )


def require_workflow_id(workflow_id: str) -> str:
    """A model-supplied id must be one build_workflow_id could have made."""
    if not is_workflow_id(workflow_id):
        raise ToolFailure(
            FailureKind.INVALID_REQUEST,
            "That is not a workflow id: ids are lowercase words joined by hyphens, at most "
            f"{MAX_WORKFLOW_ID_LENGTH} characters.",
            "Use a workflow_id exactly as list_workflows or discover_workflow returned it.",
        )
    return workflow_id


def keyed(workflow: Workflow | None, workflow_id: str, version: int | None) -> Workflow | None:
    """A record only counts as the one asked for when it names that key itself."""
    if workflow is None or workflow.workflow_id != workflow_id:
        return None
    if version is not None and workflow.version != version:
        return None
    return workflow


def refuse_oversize(workflow: Workflow) -> None:
    """A graph too large for one item is refused before the write, not by DynamoDB."""
    size = len(workflow.model_dump_json().encode())
    if size > MAX_ITEM_BYTES:
        raise ToolFailure(
            FailureKind.INVALID_REQUEST,
            f"This workflow is {size} bytes, over the {MAX_ITEM_BYTES} byte limit for one"
            " stored version.",
            "Discover a smaller part of the chain, starting from a resource further downstream.",
        )


def version_taken_failure(workflow_id: str, version: int) -> ToolFailure:
    return ToolFailure(
        FailureKind.INVALID_REQUEST,
        f"Version {version} of workflow {workflow_id!r} already exists: the workflow changed"
        " since it was shown.",
        "Run discover_workflow again, review the new proposal, and save that.",
    )


def unknown_workflow_failure(workflow_id: str, version: int | None) -> ToolFailure:
    wanted = "its latest version" if version is None else f"version {version}"
    return ToolFailure(
        FailureKind.RESOURCE_NOT_FOUND,
        f"No workflow {workflow_id!r} with {wanted} is stored.",
        "List the stored workflows with list_workflows, or discover this chain first.",
    )


def summarize(workflow: Workflow) -> WorkflowSummary:
    return WorkflowSummary(
        workflow_id=workflow.workflow_id,
        name=workflow.name,
        entry_point_arn=workflow.entry_point_arn,
        latest_version=workflow.version,
        node_count=len(workflow.nodes),
        confirmed_at=workflow.confirmed_at,
    )


def sort_summaries(summaries: list[WorkflowSummary]) -> list[WorkflowSummary]:
    return sorted(summaries, key=lambda summary: (summary.name, summary.workflow_id))
