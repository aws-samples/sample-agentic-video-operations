"""The workflow records, and the one hash that identifies a chain's shape (§8.2).

Every list is sorted here, so the same signal map always produces byte-identical records and
the same `content_sha256`. That hash is what the operator approves and what a saved version is
checked against, so it covers the graph only: not the time it was discovered, nor its name,
version or diff.
"""

import hashlib
import json
import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from agentic_iops_streaming.domain.read_arn_parts import read_arn_parts

MAX_WORKFLOW_ID_LENGTH = 64
SLUG_SEPARATORS = re.compile(r"[^a-z0-9]+")
# What build_workflow_id makes: lowercase words joined by single hyphens. An id is a store key
# and, locally, a folder name, so anything else (`..`, `/`, capitals) is not one of ours.
WORKFLOW_ID_FORMAT = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


class WorkflowNode(BaseModel):
    """One resource in the chain, as the signal map described it."""

    model_config = ConfigDict(frozen=True)

    arn: str
    service: str
    resource_type: str
    name: str
    sources: list[str] = Field(default_factory=list)
    destinations: list[str] = Field(default_factory=list)

    @classmethod
    def from_media_resource(cls, arn: str, resource: dict) -> "WorkflowNode":
        """Build a node from one `MediaResourceMap` entry (§8.3 step 3)."""
        parts = read_arn_parts(arn)
        return cls(
            arn=arn,
            service=parts.service,
            resource_type=parts.resource_type,
            name=str(resource.get("Name") or ""),
            sources=sorted({str(item.get("Arn", "")) for item in resource.get("Sources") or []}),
            destinations=sorted(
                {str(item.get("Arn", "")) for item in resource.get("Destinations") or []}
            ),
        )


class WorkflowEdge(BaseModel):
    """A source → destination link. `inferred` marks an edge the map did not list."""

    model_config = ConfigDict(frozen=True)

    source: str
    destination: str
    inferred: bool = False

    @property
    def order(self) -> tuple[str, str, bool]:
        return (self.source, self.destination, self.inferred)


class WorkflowDiff(BaseModel):
    """What changed between a fresh discovery and the latest stored version."""

    model_config = ConfigDict(frozen=True)

    against_version: int
    added_nodes: list[str] = Field(default_factory=list)
    removed_nodes: list[str] = Field(default_factory=list)
    added_edges: list[WorkflowEdge] = Field(default_factory=list)
    removed_edges: list[WorkflowEdge] = Field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        changes = (self.added_nodes, self.removed_nodes, self.added_edges, self.removed_edges)
        return not any(changes)


class WorkflowProposal(BaseModel):
    """A discovered chain, shown to the operator and not stored until approved."""

    model_config = ConfigDict(frozen=True)

    workflow_id: str
    version: int
    name: str
    entry_point_arn: str
    discovered_at: datetime
    nodes: list[WorkflowNode] = Field(default_factory=list)
    failed_nodes: list[WorkflowNode] = Field(default_factory=list)
    edges: list[WorkflowEdge] = Field(default_factory=list)
    content_sha256: str
    diff: WorkflowDiff | None = None

    @property
    def node_arns(self) -> list[str]:
        return [node.arn for node in self.nodes]


class Workflow(BaseModel):
    """A stored version: the proposal's graph plus who confirmed it, and when."""

    model_config = ConfigDict(frozen=True)

    workflow_id: str
    version: int
    name: str
    entry_point_arn: str
    discovered_at: datetime
    nodes: list[WorkflowNode] = Field(default_factory=list)
    failed_nodes: list[WorkflowNode] = Field(default_factory=list)
    edges: list[WorkflowEdge] = Field(default_factory=list)
    content_sha256: str
    confirmed_by: str
    confirmed_at: datetime

    @property
    def node_arns(self) -> list[str]:
        return [node.arn for node in self.nodes]

    @classmethod
    def from_proposal(
        cls, proposal: WorkflowProposal, *, confirmed_by: str, confirmed_at: datetime
    ) -> "Workflow":
        fields = proposal.model_dump(exclude={"diff"})
        return cls(**fields, confirmed_by=confirmed_by, confirmed_at=confirmed_at)


class WorkflowSummary(BaseModel):
    """One line per workflow in `list_workflows`, from its highest version."""

    model_config = ConfigDict(frozen=True)

    workflow_id: str
    name: str
    entry_point_arn: str
    latest_version: int
    node_count: int
    confirmed_at: datetime


def sort_nodes(nodes: list[WorkflowNode]) -> list[WorkflowNode]:
    return sorted(nodes, key=lambda node: node.arn)


def sort_edges(edges: list[WorkflowEdge]) -> list[WorkflowEdge]:
    """Sorted, and each (source, destination, inferred) at most once."""
    return sorted({edge.order: edge for edge in edges}.values(), key=lambda edge: edge.order)


def compute_content_sha256(
    *,
    entry_point_arn: str,
    nodes: list[WorkflowNode],
    failed_nodes: list[WorkflowNode],
    edges: list[WorkflowEdge],
) -> str:
    """The graph's identity (§8.2): the sorted records as canonical JSON, hashed."""
    payload = {
        "entry_point_arn": entry_point_arn,
        "nodes": [node.model_dump(mode="json") for node in sort_nodes(nodes)],
        "failed_nodes": [node.model_dump(mode="json") for node in sort_nodes(failed_nodes)],
        "edges": [edge.model_dump(mode="json") for edge in sort_edges(edges)],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def build_workflow_id(name: str, suffix: str) -> str:
    """A lowercase slug of the name plus a short suffix; never an ARN or resource id."""
    slug = SLUG_SEPARATORS.sub("-", name.lower()).strip("-") or "workflow"
    room = MAX_WORKFLOW_ID_LENGTH - len(suffix) - 1
    return f"{slug[:room].rstrip('-')}-{suffix}"


def describe_version(version: int, content_sha256: str) -> str:
    """The `ActionResult` state text of one stored version (§8.1 step 5)."""
    return f"v{version} {content_sha256[:12]}"
