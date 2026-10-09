"""Store the version the operator approved, and nothing else (§8.1 step 5).

The approval signs four strings, not a graph: the model can't hand over a different chain. The
save refuses unless the signed fields are exactly the passed ones (`require_signed_parameters`),
and the passed ones are the session proposal's, with its hash recomputed from the graph. What is
stored is therefore exactly what was shown.
"""

from collections.abc import Callable, Mapping
from datetime import datetime

from agentic_iops_streaming.domain.workflow_records import (
    Workflow,
    WorkflowProposal,
    compute_content_sha256,
    describe_version,
)
from agentic_iops_streaming.domain.workflow_store import (
    VersionAlreadyExists,
    WorkflowStore,
    require_workflow_id,
    version_taken_failure,
)
from media_ops_contracts.action_result import ActionResult
from media_ops_contracts.approved_action import ApprovedAction
from media_ops_contracts.require_action_approval import require_action_approval
from media_ops_contracts.require_signed_parameters import require_signed_parameters
from media_ops_contracts.tool_failure import FailureKind, ToolFailure

ACTION = "save_workflow"
ABSENT = "absent"
NOT_READ_BACK = "not read back: the store returned no item"


def save_workflow(
    store: WorkflowStore,
    proposals: Mapping[str, WorkflowProposal],
    *,
    workflow_id: str,
    version: str,
    entry_point_arn: str,
    name: str,
    content_sha256: str,
    approved_action: ApprovedAction,
    signing_key: bytes,
    now: Callable[[], datetime],
) -> ActionResult:
    """Verify the approval and the proposal, write one version, and read it back."""
    require_action_approval(
        approved_action,
        action=ACTION,
        signing_key=signing_key,
        now=now(),
        resource_id=workflow_id,
    )
    require_signed_parameters(
        approved_action,
        {
            "version": version,
            "entry_point_arn": entry_point_arn,
            "name": name,
            "content_sha256": content_sha256,
        },
    )
    proposal = proposals.get(require_workflow_id(workflow_id))
    if proposal is None:
        raise ToolFailure(
            FailureKind.RESOURCE_NOT_FOUND,
            f"No proposal for workflow {workflow_id!r} is held in this session.",
            "Run discover_workflow first, then save the proposal it returns.",
        )
    check_matches_proposal(
        proposal,
        version=version,
        entry_point_arn=entry_point_arn,
        name=name,
        content_sha256=content_sha256,
    )
    before = store.read(workflow_id)
    workflow = Workflow.from_proposal(
        proposal, confirmed_by=approved_action.actor_id, confirmed_at=now()
    )
    try:
        stored = store.save(workflow)
    except VersionAlreadyExists as taken:
        raise version_taken_failure(workflow_id, proposal.version) from taken
    return ActionResult(
        approval_id=approved_action.approval_id,
        action=ACTION,
        resource_id=workflow_id,
        before_state=describe_version(before.version, before.content_sha256) if before else ABSENT,
        # Only what was read back verifies the save; an absent read-back says so.
        after_state=(
            describe_version(stored.version, stored.content_sha256)
            if stored is not None
            else f"v{proposal.version} {NOT_READ_BACK}"
        ),
        verified=stored is not None
        and stored.version == proposal.version
        and stored.content_sha256 == content_sha256,
    )


def check_matches_proposal(
    proposal: WorkflowProposal,
    *,
    version: str,
    entry_point_arn: str,
    name: str,
    content_sha256: str,
) -> None:
    """What this call passed must be what the session's proposal holds, its hash recomputed.

    `require_signed_parameters` has already tied the passed values to the signed ones. This is
    the half it can't see: the graph lives only in the session, so this is what stops a save
    storing a version, name or chain other than the one the operator was shown.
    """
    recomputed = compute_content_sha256(
        entry_point_arn=proposal.entry_point_arn,
        nodes=proposal.nodes,
        failed_nodes=proposal.failed_nodes,
        edges=proposal.edges,
    )
    mismatches = [
        field
        for field, passed, held in (
            ("version", version, str(proposal.version)),
            ("entry_point_arn", entry_point_arn, proposal.entry_point_arn),
            ("name", name, proposal.name),
            ("content_sha256", content_sha256, recomputed),
        )
        if passed != held
    ]
    if mismatches:
        raise ToolFailure(
            FailureKind.INVALID_REQUEST,
            f"This save does not match this session's proposal ({', '.join(mismatches)}"
            " differ), so nothing was stored.",
            "Run discover_workflow again, review the new proposal, and save that.",
        )
