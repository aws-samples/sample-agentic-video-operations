"""The local workflow store: one JSON file per version under the ignored `.cache/` (§8.4).

Used by `just run agentic-iops-streaming` and the demo, where there is no table. A save
creates its file exclusively, which is the local form of DynamoDB's `attribute_not_exists`.

`get_workflow` passes a model-supplied id, so the id must be a generated slug, and every path
is resolved and must stay inside the resolved root: `../`, a symlinked folder or a symlinked
file is refused. A file whose record names another key is not that workflow.
"""

import json
from pathlib import Path

from agentic_iops_streaming.domain.workflow_records import Workflow, WorkflowSummary
from agentic_iops_streaming.domain.workflow_store import (
    VersionAlreadyExists,
    is_workflow_id,
    keyed,
    refuse_oversize,
    require_workflow_id,
    sort_summaries,
    summarize,
)
from media_ops_contracts.tool_failure import FailureKind, ToolFailure

DEFAULT_WORKFLOW_DIR = Path(".cache/workflows")


class LocalWorkflowStore:
    """Workflows as files: `<root>/<workflow_id>/v<version>.json`."""

    def __init__(self, root: Path = DEFAULT_WORKFLOW_DIR) -> None:
        self.root = root

    def save(self, workflow: Workflow) -> Workflow | None:
        refuse_oversize(workflow)
        folder = self.folder_of(workflow.workflow_id)
        folder.mkdir(parents=True, exist_ok=True)
        path = self.path_of(workflow.workflow_id, workflow.version)
        try:
            with path.open("x") as file:  # exclusive: never overwrite a stored version
                file.write(workflow.model_dump_json())
        except FileExistsError as error:
            raise VersionAlreadyExists(workflow.workflow_id) from error
        return self.read(workflow.workflow_id, workflow.version)  # None: nothing read back

    def read(self, workflow_id: str, version: int | None = None) -> Workflow | None:
        versions = self.versions_of(workflow_id)
        if version is None:
            return self.load(workflow_id, versions[-1]) if versions else None
        return self.load(workflow_id, version) if version in versions else None

    def summaries(self, contains_arn: str | None = None) -> list[WorkflowSummary]:
        summaries = []
        for folder in sorted(self.root.glob("*")):
            if not is_workflow_id(folder.name) or not self.is_inside(folder):
                continue  # not a workflow folder of this store
            latest = self.read(folder.name)
            if latest is not None and (
                contains_arn is None
                or contains_arn in latest.node_arns
                or contains_arn == latest.entry_point_arn
            ):
                summaries.append(summarize(latest))
        return sort_summaries(summaries)

    def folder_of(self, workflow_id: str) -> Path:
        return self.inside(self.root / require_workflow_id(workflow_id))

    def path_of(self, workflow_id: str, version: int) -> Path:
        return self.inside(self.folder_of(workflow_id) / f"v{version}.json")

    def is_inside(self, path: Path) -> bool:
        return path.resolve().is_relative_to(self.root.resolve())

    def inside(self, path: Path) -> Path:
        """The path, when it resolves inside the resolved root (symlinks followed)."""
        if not self.is_inside(path):
            raise ToolFailure(
                FailureKind.INVALID_REQUEST,
                "That workflow path resolves outside the workflow store, so it is not read.",
                "Use a workflow_id exactly as list_workflows or discover_workflow returned it.",
            )
        return path

    def versions_of(self, workflow_id: str) -> list[int]:
        folder = self.folder_of(workflow_id)
        if not folder.is_dir():
            return []
        versions = []
        for path in folder.glob("v*.json"):
            number = path.stem.removeprefix("v")
            if number.isdigit():
                versions.append(int(number))
        return sorted(versions)

    def load(self, workflow_id: str, version: int) -> Workflow | None:
        path = self.path_of(workflow_id, version)
        try:
            record = Workflow.model_validate(json.loads(path.read_text()))
        except (OSError, ValueError):
            return None  # an unreadable file is treated as absent, never as a partial workflow
        return keyed(record, workflow_id, version)
