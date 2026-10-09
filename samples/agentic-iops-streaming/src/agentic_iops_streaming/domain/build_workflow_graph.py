"""Turn one signal map's resource maps into sorted nodes and edges (§8.3 step 3).

A pure decision: it reads the API's two maps and returns records, with no AWS client and no
clock of its own. Every key of `MediaResourceMap` becomes a node, and every source and
destination pair becomes one edge, so a link named from both ends appears once.
"""

from dataclasses import dataclass
from typing import Any

from agentic_iops_streaming.domain.workflow_records import (
    WorkflowEdge,
    WorkflowNode,
    sort_edges,
    sort_nodes,
)


@dataclass(frozen=True)
class WorkflowGraph:
    nodes: list[WorkflowNode]
    failed_nodes: list[WorkflowNode]
    edges: list[WorkflowEdge]


def build_workflow_graph(
    media_resource_map: dict[str, Any] | None,
    failed_media_resource_map: dict[str, Any] | None = None,
) -> WorkflowGraph:
    nodes = read_nodes(media_resource_map)
    return WorkflowGraph(
        nodes=nodes,
        failed_nodes=read_nodes(failed_media_resource_map),
        edges=read_edges(nodes),
    )


def read_nodes(resource_map: dict[str, Any] | None) -> list[WorkflowNode]:
    return sort_nodes(
        [
            WorkflowNode.from_media_resource(arn, resource or {})
            for arn, resource in (resource_map or {}).items()
            if arn
        ]
    )


def read_edges(nodes: list[WorkflowNode]) -> list[WorkflowEdge]:
    """Both directions of the map describe the same links, so collect them once."""
    edges = [
        WorkflowEdge(source=node.arn, destination=destination)
        for node in nodes
        for destination in node.destinations
        if destination
    ]
    edges += [
        WorkflowEdge(source=source, destination=node.arn)
        for node in nodes
        for source in node.sources
        if source
    ]
    return sort_edges(edges)
