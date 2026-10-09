"""The coordinator's own four workflow tools (§8.1).

These belong to the coordinator, not to a domain pack: a pack stays single-service, while a
workflow spans several. `save_workflow` is a `WriteTool`, so it takes the same §4 route as every
pack write, with `workflow_id` as the resource; discovery needs no approval because it leaves
nothing in the account.

The functions here stay framework-free. Two inputs are injected by `wrap_workflow_tools`, never
by the model: the session's held proposals, and the signed `ApprovedAction`. Function names are the
tool names.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from agentic_iops_streaming.adapters.signal_maps.discover_signal_map import DiscoveryPolicy
from agentic_iops_streaming.domain.workflow_records import (
    Workflow,
    WorkflowProposal,
    WorkflowSummary,
)
from agentic_iops_streaming.domain.workflow_store import WorkflowStore
from agentic_iops_streaming.settings.runtime_settings import AgenticIopsSettings
from agentic_iops_streaming.workflows import discover_workflow as discovery
from agentic_iops_streaming.workflows import read_workflows as stored
from agentic_iops_streaming.workflows import save_workflow as saving
from media_ops_contracts.action_result import ActionResult
from media_ops_contracts.approved_action import ApprovedAction
from media_ops_contracts.create_aws_client import create_aws_client
from media_ops_contracts.domain_pack import ReadTool, WriteTool
from media_ops_contracts.read_utc_now import read_utc_now


@dataclass(frozen=True)
class WorkflowTools:
    """The coordinator's tools: reads the model may call freely, and the one approved write."""

    reads: list[ReadTool]
    writes: list[WriteTool]

    @property
    def is_empty(self) -> bool:
        return not (self.reads or self.writes)


def create_workflow_tools(
    settings: AgenticIopsSettings,
    store: WorkflowStore,
    *,
    signing_key: bytes,
    medialive: Any | None = None,
    now: Callable[[], datetime] = read_utc_now,
    policy: DiscoveryPolicy | None = None,
    suffix: str | None = None,
) -> WorkflowTools:
    """The four tools, or none at all when ALLOW_WORKFLOW_DISCOVERY is off.

    `now` is the clock the save checks its approval against, so it must be the agent's clock.
    `suffix` pins a new workflow's id for tests and evals; left unset, each id gets a random one.
    """
    if not settings.allow_workflow_discovery:
        return WorkflowTools(reads=[], writes=[])

    def build_medialive() -> Any:
        if medialive is not None:
            return medialive
        return create_aws_client(
            "medialive",
            region=settings.aws_region,
            demo=settings.demo,
            demo_scenario=settings.demo_scenario,
            fixtures_dir=settings.fixtures_dir,
        )

    def discover_workflow(entry_point_arn: str, name: str) -> WorkflowProposal:
        """Map the live chain below one flow, channel or endpoint ARN and propose a workflow.

        Creates a temporary signal map, reads the resources it connects, then deletes it, so
        nothing is left in the account. Nothing is stored: show the operator the proposed
        chain, then call save_workflow to keep it. Rediscovering a known chain reports a diff.
        """
        return discovery.discover_workflow(
            build_medialive(),
            store,
            entry_point_arn=entry_point_arn,
            name=name,
            now=now,
            policy=policy,
            suffix=suffix,
        )

    def save_workflow(
        workflow_id: str,
        version: str,
        entry_point_arn: str,
        name: str,
        content_sha256: str,
        approved_action: ApprovedAction,
        proposals: Mapping[str, WorkflowProposal],
    ) -> ActionResult:
        """Store the workflow this session discovered, as a new immutable version.

        Pass workflow_id, version, entry_point_arn, name and content_sha256 exactly as
        discover_workflow returned them. The chain itself comes from this session's proposal,
        so what is stored is what the operator approved.
        """
        return saving.save_workflow(
            store,
            proposals,
            workflow_id=workflow_id,
            version=version,
            entry_point_arn=entry_point_arn,
            name=name,
            content_sha256=content_sha256,
            approved_action=approved_action,
            signing_key=signing_key,
            now=now,
        )

    def list_workflows(contains_arn: str | None = None) -> list[WorkflowSummary]:
        """List the stored workflows, each at its newest version.

        With contains_arn, only those whose latest version contains that resource: this is how
        one channel or flow finds the chain it belongs to.
        """
        return stored.list_workflows(store, contains_arn)

    def get_workflow(workflow_id: str, version: int | None = None) -> Workflow:
        """Read one stored workflow: its nodes, edges, and who confirmed it when.

        Without a version, the latest. Load this before monitoring a chain, so the walk follows
        the known path instead of guessing it.
        """
        return stored.get_workflow(store, workflow_id, version)

    return WorkflowTools(
        reads=[discover_workflow, list_workflows, get_workflow],
        writes=[WriteTool(function=save_workflow, resource_parameter="workflow_id")],
    )
