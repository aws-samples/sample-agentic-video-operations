"""What a fresh discovery changed against the latest stored version (§8.2).

A pure comparison of two graphs by ARN and by edge, so a rediscovery says what moved rather
than only that the hash differs.
"""

from agentic_iops_streaming.domain.build_workflow_graph import WorkflowGraph
from agentic_iops_streaming.domain.workflow_records import (
    Workflow,
    WorkflowDiff,
    WorkflowEdge,
    sort_edges,
)


def diff_workflows(stored: Workflow, discovered: WorkflowGraph) -> WorkflowDiff:
    before_nodes = {node.arn for node in stored.nodes}
    after_nodes = {node.arn for node in discovered.nodes}
    before_edges = {edge.order: edge for edge in stored.edges}
    after_edges = {edge.order: edge for edge in discovered.edges}
    return WorkflowDiff(
        against_version=stored.version,
        added_nodes=sorted(after_nodes - before_nodes),
        removed_nodes=sorted(before_nodes - after_nodes),
        added_edges=edges_of(after_edges, set(after_edges) - set(before_edges)),
        removed_edges=edges_of(before_edges, set(before_edges) - set(after_edges)),
    )


def edges_of(
    edges: dict[tuple[str, str, bool], WorkflowEdge], keys: set[tuple[str, str, bool]]
) -> list[WorkflowEdge]:
    return sort_edges([edges[key] for key in keys])
