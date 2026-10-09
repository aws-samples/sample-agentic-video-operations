"""Discovery, cleanup and the save contract (§8.1, §8.3, §8.4).

The signal map is a transient engine, so the sharpest rules are about what is left behind and
what is stored: every outcome of the §8.3 table, and a save that stores only what was approved.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from agentic_iops_streaming.adapters.signal_maps.discover_signal_map import DiscoveryPolicy
from agentic_iops_streaming.adapters.workflow_store.local_workflow_store import LocalWorkflowStore
from agentic_iops_streaming.domain.workflow_records import Workflow
from agentic_iops_streaming.workflows.discover_workflow import discover_workflow
from agentic_iops_streaming.workflows.read_workflows import get_workflow, list_workflows
from agentic_iops_streaming.workflows.save_workflow import save_workflow
from media_ops_contracts.approved_action import ActionProposal, sign_approved_action
from media_ops_contracts.replay_fixture_client import ReplayFixtureClient
from media_ops_contracts.tool_failure import FailureKind, ToolFailure

FIXTURES = Path(__file__).resolve().parents[4] / "fixtures"
FLOW = "arn:aws:mediaconnect:us-west-2:111122223333:flow:demo-contribution:flow-1"
CHANNEL = "arn:aws:medialive:us-west-2:111122223333:channel:1234567"
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
KEY = b"workflow-signing-key"
FAST = DiscoveryPolicy(deadline_seconds=30, interval_seconds=1, sleep=lambda _: None)


def clock():
    return NOW


def replay(scenario: str) -> ReplayFixtureClient:
    return ReplayFixtureClient("medialive", scenario=scenario, fixtures_dir=FIXTURES)


def store(tmp_path: Path) -> LocalWorkflowStore:
    return LocalWorkflowStore(tmp_path / "workflows")


def discover(medialive, workflow_store, *, name="demo chain", entry=FLOW):
    return discover_workflow(
        medialive,
        workflow_store,
        entry_point_arn=entry,
        name=name,
        now=clock,
        policy=FAST,
        suffix="ab12cd",
    )


def approval_for(proposal, *, action="save_workflow", key=KEY, actor="operator-1", **changes):
    parameters = {
        "version": str(proposal.version),
        "entry_point_arn": proposal.entry_point_arn,
        "name": proposal.name,
        "content_sha256": proposal.content_sha256,
    } | changes
    return sign_approved_action(
        ActionProposal(
            actor_id=actor,
            action=action,
            resource_id=changes.get("resource_id", proposal.workflow_id),
            parameters={key: value for key, value in parameters.items() if key != "resource_id"},
        ),
        approval_id="approval-1",
        expires_at=datetime(2026, 10, 6, 12, 10, tzinfo=UTC),
        signing_key=key,
    )


def save(workflow_store, proposal, approval, *, key=KEY, **changes):
    inputs = {
        "workflow_id": proposal.workflow_id,
        "version": str(proposal.version),
        "entry_point_arn": proposal.entry_point_arn,
        "name": proposal.name,
        "content_sha256": proposal.content_sha256,
    } | changes
    return save_workflow(
        workflow_store,
        {proposal.workflow_id: proposal},
        **inputs,
        approved_action=approval,
        signing_key=key,
        now=clock,
    )


# --- discovery -----------------------------------------------------------------------------


def test_discovery_returns_the_recorded_chain_and_deletes_its_map(tmp_path):
    medialive = replay("workflow_discovery")

    proposal = discover(medialive, store(tmp_path))

    services = [node.service for node in proposal.nodes]
    assert services == ["cloudfront", "mediaconnect", "medialive", "mediapackage"]
    assert proposal.version == 1 and proposal.diff is None
    assert len(proposal.edges) == 3 and proposal.content_sha256
    called = [name for name, _ in medialive.calls]
    assert called.count("create_signal_map") == 1
    assert called.count("delete_signal_map") == 1  # deleted, and its absence verified
    assert called[-1] == "get_signal_map"


def test_the_flow_to_flow_chain_is_discovered_the_same_way(tmp_path):
    proposal = discover(replay("workflow_flow_to_flow"), store(tmp_path))

    assert [node.service for node in proposal.nodes] == ["mediaconnect", "mediaconnect"]
    assert len(proposal.edges) == 1


def test_discovering_an_unchanged_chain_again_reuses_the_id_and_bumps_the_version(tmp_path):
    workflow_store = store(tmp_path)
    first = discover(replay("workflow_discovery"), workflow_store)
    save(workflow_store, first, approval_for(first))

    again = discover(replay("workflow_discovery"), workflow_store)

    assert again.workflow_id == first.workflow_id
    assert again.version == 2
    assert again.content_sha256 == first.content_sha256
    assert again.diff is not None and again.diff.is_empty and again.diff.against_version == 1


def test_a_changed_chain_carries_a_diff_against_the_stored_version(tmp_path):
    workflow_store = store(tmp_path)
    first = discover(replay("workflow_discovery"), workflow_store)
    save(workflow_store, first, approval_for(first))

    shorter = discover(replay("workflow_flow_to_flow"), workflow_store, entry=FLOW)

    assert shorter.workflow_id == first.workflow_id and shorter.version == 2
    assert shorter.diff is not None and not shorter.diff.is_empty
    assert CHANNEL in shorter.diff.removed_nodes


# --- the §8.3 outcome table ----------------------------------------------------------------


class FakeMediaLive:
    """One signal map, scripted: how it discovers, deletes, and answers after the delete."""

    def __init__(self, *, statuses=("CREATE_COMPLETE",), delete=None, after_delete="gone"):
        self.statuses = list(statuses)
        self.delete = delete
        self.after_delete = after_delete
        self.calls: list[str] = []
        self.deleted = False

    def create_signal_map(self, **_):
        self.calls.append("create_signal_map")
        return {"Id": "sm-1", "Status": "CREATE_IN_PROGRESS"}

    def get_signal_map(self, **_):
        self.calls.append("get_signal_map")
        if self.deleted:
            if self.after_delete == "gone":
                raise client_error("NotFoundException", "GetSignalMap")
            if self.after_delete == "denied":
                raise client_error("AccessDeniedException", "GetSignalMap")
            return {"Id": "sm-1", "Status": "CREATE_COMPLETE", "MediaResourceMap": {}}
        status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        return {
            "Id": "sm-1",
            "Status": status,
            "ErrorMessage": "entry point not found" if status == "CREATE_FAILED" else None,
            "MediaResourceMap": {FLOW: {"Name": "demo", "Destinations": [{"Arn": CHANNEL}]}},
            "FailedMediaResourceMap": {},
        }

    def delete_signal_map(self, **_):
        self.calls.append("delete_signal_map")
        if self.delete is not None:
            raise client_error(self.delete, "DeleteSignalMap")
        self.deleted = True
        return {}


def client_error(code: str, operation: str):
    from botocore.exceptions import ClientError

    return ClientError({"Error": {"Code": code, "Message": code}}, operation)


def test_success_with_a_verified_delete_returns_the_proposal(tmp_path):
    medialive = FakeMediaLive()
    proposal = discover(medialive, store(tmp_path))
    assert proposal.nodes and "delete_signal_map" in medialive.calls


def test_success_with_a_failed_delete_is_a_failure_that_names_the_map(tmp_path):
    medialive = FakeMediaLive(delete="AccessDeniedException")

    with pytest.raises(ToolFailure) as failure:
        discover(medialive, store(tmp_path))

    assert failure.value.kind is FailureKind.PERMISSION_DENIED
    assert "Signal map 'sm-1' was not deleted" in failure.value.message
    assert "delete-signal-map --identifier sm-1" in failure.value.next_action


def test_a_post_delete_read_that_is_refused_is_not_proof_the_map_is_gone(tmp_path):
    with pytest.raises(ToolFailure) as failure:
        discover(FakeMediaLive(after_delete="denied"), store(tmp_path))
    assert failure.value.kind is FailureKind.PERMISSION_DENIED
    assert "was not deleted" in failure.value.message


def test_a_map_still_readable_after_the_delete_is_a_cleanup_failure(tmp_path):
    with pytest.raises(ToolFailure) as failure:
        discover(FakeMediaLive(after_delete="still there"), store(tmp_path))
    assert failure.value.kind is FailureKind.UNEXPECTED_FAILURE


def test_a_failed_discovery_is_reported_and_the_map_is_still_deleted(tmp_path):
    medialive = FakeMediaLive(statuses=("CREATE_FAILED",))

    with pytest.raises(ToolFailure) as failure:
        discover(medialive, store(tmp_path))

    assert failure.value.kind is FailureKind.EXTERNAL_SERVICE_UNAVAILABLE
    assert "entry point not found" in failure.value.message
    assert "delete_signal_map" in medialive.calls
    assert "was not deleted" not in failure.value.message


def test_both_failing_gives_the_primary_failure_with_the_cleanup_attached(tmp_path):
    medialive = FakeMediaLive(statuses=("CREATE_FAILED",), delete="ThrottlingException")

    with pytest.raises(ToolFailure) as failure:
        discover(medialive, store(tmp_path))

    assert failure.value.kind is FailureKind.EXTERNAL_SERVICE_UNAVAILABLE
    assert "Discovery failed" in failure.value.message
    assert "Signal map 'sm-1' was not deleted" in failure.value.message
    assert "delete-signal-map" in failure.value.next_action


def test_a_discovery_that_never_completes_stops_at_the_deadline(tmp_path):
    clock_values = iter([0.0, 0.0, 10.0, 20.0, 40.0, 60.0])
    policy = DiscoveryPolicy(
        deadline_seconds=30,
        interval_seconds=1,
        sleep=lambda _: None,
        monotonic=lambda: next(clock_values),
    )
    medialive = FakeMediaLive(statuses=("CREATE_IN_PROGRESS",))

    with pytest.raises(ToolFailure) as failure:
        discover_workflow(
            medialive,
            store(tmp_path),
            entry_point_arn=FLOW,
            name="demo",
            now=clock,
            policy=policy,
            suffix="ab12cd",
        )

    assert failure.value.kind is FailureKind.EXTERNAL_SERVICE_UNAVAILABLE
    assert "did not finish" in failure.value.message
    assert "delete_signal_map" in medialive.calls  # the deadline still cleans up


# --- save ----------------------------------------------------------------------------------


def test_an_approved_save_stores_one_version_and_verifies_the_read_back(tmp_path):
    workflow_store = store(tmp_path)
    proposal = discover(replay("workflow_discovery"), workflow_store)

    result = save(workflow_store, proposal, approval_for(proposal))

    assert (result.action, result.resource_id, result.verified) == (
        "save_workflow",
        proposal.workflow_id,
        True,
    )
    assert result.before_state == "absent"
    assert result.after_state == f"v1 {proposal.content_sha256[:12]}"
    stored = get_workflow(workflow_store, proposal.workflow_id)
    assert stored.confirmed_by == "operator-1" and stored.version == 1


def test_a_second_save_records_the_version_it_replaced(tmp_path):
    workflow_store = store(tmp_path)
    first = discover(replay("workflow_discovery"), workflow_store)
    save(workflow_store, first, approval_for(first))
    second = discover(replay("workflow_flow_to_flow"), workflow_store)

    result = save(workflow_store, second, approval_for(second))

    assert result.before_state == f"v1 {first.content_sha256[:12]}"
    assert result.after_state == f"v2 {second.content_sha256[:12]}"
    assert result.verified


@pytest.mark.parametrize(
    ("label", "changes"),
    [
        ("another workflow", {"resource_id": "other-workflow-zz99"}),
        ("another action", {"action": "forget_workflow"}),
        ("another hash", {"content_sha256": "0" * 64}),
        ("another version", {"version": "7"}),
        ("another entry point", {"entry_point_arn": CHANNEL}),
        ("another name", {"name": "something else"}),
    ],
)
def test_an_approval_that_does_not_match_the_proposal_stores_nothing(tmp_path, label, changes):
    workflow_store = store(tmp_path)
    proposal = discover(replay("workflow_discovery"), workflow_store)
    approval = approval_for(proposal, **changes)

    with pytest.raises(ToolFailure) as failure:
        save(workflow_store, proposal, approval)

    assert failure.value.kind is FailureKind.APPROVAL_REQUIRED  # refused as an approval
    assert workflow_store.read(proposal.workflow_id) is None


def test_an_approval_signing_an_extra_input_stores_nothing(tmp_path):
    """require_signed_parameters: the signed inputs are exactly the save's, none added."""
    workflow_store = store(tmp_path)
    proposal = discover(replay("workflow_discovery"), workflow_store)

    with pytest.raises(ToolFailure) as failure:
        save(workflow_store, proposal, approval_for(proposal, overwrite="true"))

    assert failure.value.kind is FailureKind.APPROVAL_REQUIRED
    assert "overwrite" in failure.value.message
    assert workflow_store.read(proposal.workflow_id) is None


def test_inputs_signed_and_passed_alike_but_unlike_the_proposal_store_nothing(tmp_path):
    """The check the helper can't make: the call and its approval agree, the session doesn't."""
    workflow_store = store(tmp_path)
    proposal = discover(replay("workflow_discovery"), workflow_store)

    with pytest.raises(ToolFailure) as failure:
        save(
            workflow_store,
            proposal,
            approval_for(proposal, name="renamed"),
            name="renamed",
        )

    assert failure.value.kind is FailureKind.INVALID_REQUEST
    assert "name" in failure.value.message
    assert workflow_store.read(proposal.workflow_id) is None


def test_a_forged_or_expired_approval_stores_nothing(tmp_path):
    workflow_store = store(tmp_path)
    proposal = discover(replay("workflow_discovery"), workflow_store)

    with pytest.raises(ToolFailure) as forged:
        save(workflow_store, proposal, approval_for(proposal, key=b"other-key"))
    assert forged.value.kind is FailureKind.APPROVAL_REQUIRED

    late = sign_approved_action(
        ActionProposal(
            actor_id="operator-1",
            action="save_workflow",
            resource_id=proposal.workflow_id,
            parameters={
                "version": "1",
                "entry_point_arn": proposal.entry_point_arn,
                "name": proposal.name,
                "content_sha256": proposal.content_sha256,
            },
        ),
        approval_id="approval-1",
        expires_at=datetime(2026, 10, 6, 11, 0, tzinfo=UTC),
        signing_key=KEY,
    )
    with pytest.raises(ToolFailure) as expired:
        save(workflow_store, proposal, late)
    assert expired.value.kind is FailureKind.APPROVAL_EXPIRED
    assert workflow_store.read(proposal.workflow_id) is None


def test_a_save_without_a_proposal_in_this_session_stores_nothing(tmp_path):
    workflow_store = store(tmp_path)
    proposal = discover(replay("workflow_discovery"), workflow_store)

    with pytest.raises(ToolFailure) as failure:
        save_workflow(
            workflow_store,
            {},  # a later request in a session that never discovered
            workflow_id=proposal.workflow_id,
            version="1",
            entry_point_arn=proposal.entry_point_arn,
            name=proposal.name,
            content_sha256=proposal.content_sha256,
            approved_action=approval_for(proposal),
            signing_key=KEY,
            now=clock,
        )

    assert failure.value.kind is FailureKind.RESOURCE_NOT_FOUND
    assert workflow_store.read(proposal.workflow_id) is None


def test_a_version_another_save_took_first_is_refused(tmp_path):
    workflow_store = store(tmp_path)
    proposal = discover(replay("workflow_discovery"), workflow_store)
    save(workflow_store, proposal, approval_for(proposal))

    with pytest.raises(ToolFailure) as failure:
        save(workflow_store, proposal, approval_for(proposal))

    assert failure.value.kind is FailureKind.INVALID_REQUEST
    assert "already exists" in failure.value.message
    assert workflow_store.read(proposal.workflow_id, 1).content_sha256 == proposal.content_sha256


def test_a_read_back_that_differs_is_reported_unverified_with_the_stored_hash(tmp_path):
    """§8.1 step 5: after_state carries the observed hash, so a mismatch is visible."""
    workflow_store = store(tmp_path)
    proposal = discover(replay("workflow_discovery"), workflow_store)

    class DriftingStore(LocalWorkflowStore):
        def save(self, workflow: Workflow) -> Workflow:
            super().save(workflow)
            return workflow.model_copy(update={"content_sha256": "f" * 64})

    drifting = DriftingStore(tmp_path / "workflows")
    result = save(drifting, proposal, approval_for(proposal))

    assert result.verified is False
    assert result.after_state == f"v1 {'f' * 12}"


# --- reads ---------------------------------------------------------------------------------


def test_listing_gives_one_summary_per_workflow_at_its_latest_version(tmp_path):
    workflow_store = store(tmp_path)
    first = discover(replay("workflow_discovery"), workflow_store)
    save(workflow_store, first, approval_for(first))
    second = discover(replay("workflow_flow_to_flow"), workflow_store)
    save(workflow_store, second, approval_for(second))

    [summary] = list_workflows(workflow_store)

    assert summary.workflow_id == first.workflow_id
    assert summary.latest_version == 2 and summary.node_count == 2


def test_contains_arn_finds_a_workflow_from_any_node_and_nothing_for_an_unknown_arn(tmp_path):
    workflow_store = store(tmp_path)
    proposal = discover(replay("workflow_discovery"), workflow_store)
    save(workflow_store, proposal, approval_for(proposal))

    assert len(list_workflows(workflow_store, contains_arn=CHANNEL)) == 1
    assert len(list_workflows(workflow_store, contains_arn=FLOW)) == 1
    assert list_workflows(workflow_store, contains_arn="arn:aws:medialive:::channel:999") == []


def test_getting_an_unknown_workflow_or_version_is_resource_not_found(tmp_path):
    workflow_store = store(tmp_path)
    proposal = discover(replay("workflow_discovery"), workflow_store)
    save(workflow_store, proposal, approval_for(proposal))

    assert get_workflow(workflow_store, proposal.workflow_id, 1).version == 1
    for workflow_id, version in ((proposal.workflow_id, 9), ("no-such-workflow", None)):
        with pytest.raises(ToolFailure) as failure:
            get_workflow(workflow_store, workflow_id, version)
        assert failure.value.kind is FailureKind.RESOURCE_NOT_FOUND
