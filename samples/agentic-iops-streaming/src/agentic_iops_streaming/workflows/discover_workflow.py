"""Propose a workflow from one transient signal map (§8.1, §8.3).

Discovery proposes and never stores, so it needs no approval: it leaves nothing in the account.
When a stored workflow already contains the entry point, the proposal reuses that workflow's id
and carries a diff against its latest version, which is how a rebuild is reported.
"""

import secrets
from collections.abc import Callable
from datetime import datetime
from typing import Any

from agentic_iops_streaming.adapters.signal_maps.discover_signal_map import (
    DiscoveryPolicy,
    discover_signal_map,
)
from agentic_iops_streaming.domain.build_workflow_graph import build_workflow_graph
from agentic_iops_streaming.domain.diff_workflows import diff_workflows
from agentic_iops_streaming.domain.workflow_records import (
    WorkflowProposal,
    build_workflow_id,
    compute_content_sha256,
)
from agentic_iops_streaming.domain.workflow_store import WorkflowStore

SUFFIX_BYTES = 3  # six hex characters, enough to keep two chains of the same name apart


def discover_workflow(
    medialive: Any,
    store: WorkflowStore,
    *,
    entry_point_arn: str,
    name: str,
    now: Callable[[], datetime],
    policy: DiscoveryPolicy | None = None,
    suffix: str | None = None,
) -> WorkflowProposal:
    """Map the chain below `entry_point_arn` and return what a save would store."""
    existing = find_workflow_containing(store, entry_point_arn)
    workflow_id = (
        existing.workflow_id
        if existing
        else build_workflow_id(name, suffix or secrets.token_hex(SUFFIX_BYTES))
    )
    reading = discover_signal_map(
        medialive, entry_point_arn=entry_point_arn, workflow_id=workflow_id, policy=policy
    )
    graph = build_workflow_graph(reading.media_resource_map, reading.failed_media_resource_map)
    return WorkflowProposal(
        workflow_id=workflow_id,
        version=existing.version + 1 if existing else 1,
        name=name or workflow_id,
        entry_point_arn=entry_point_arn,
        discovered_at=now(),
        nodes=graph.nodes,
        failed_nodes=graph.failed_nodes,
        edges=graph.edges,
        content_sha256=compute_content_sha256(
            entry_point_arn=entry_point_arn,
            nodes=graph.nodes,
            failed_nodes=graph.failed_nodes,
            edges=graph.edges,
        ),
        diff=diff_workflows(existing, graph) if existing else None,
    )


def find_workflow_containing(store: WorkflowStore, arn: str):
    """The stored workflow whose latest version holds this ARN, if there is one."""
    matches = store.summaries(arn)
    return store.read(matches[0].workflow_id) if matches else None
