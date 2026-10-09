"""The deployed workflow store over one table (§8.4).

A fake client records what reaches DynamoDB, so these pin the parts a live table would
otherwise be the first to show: the conditional write, reserved-word aliasing, and a scan
that follows every page.
"""

from datetime import UTC, datetime

import pytest
from botocore.exceptions import ClientError
from test_workflow_discovery import approval_for, discover, replay, save

from agentic_iops_streaming.adapters.workflow_store.dynamodb_workflow_store import (
    DynamoDbWorkflowStore,
    build_item,
)
from agentic_iops_streaming.domain.workflow_records import Workflow, WorkflowNode
from agentic_iops_streaming.domain.workflow_store import MAX_ITEM_BYTES, VersionAlreadyExists
from agentic_iops_streaming.workflows.read_workflows import list_workflows
from media_ops_contracts.tool_failure import FailureKind, ToolFailure

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
FLOW = "arn:aws:mediaconnect:us-west-2:111122223333:flow:demo:flow-1"
CHANNEL = "arn:aws:medialive:us-west-2:111122223333:channel:1234567"
TABLE = "WorkflowTable"


def workflow(version: int = 1, nodes: int = 2, workflow_id: str = "demo-chain-ab12cd") -> Workflow:
    built = [
        WorkflowNode(
            arn=f"{CHANNEL}{index or ''}",
            service="medialive",
            resource_type="channel",
            name=f"channel-{index}",
        )
        for index in range(nodes)
    ]
    return Workflow(
        workflow_id=workflow_id,
        version=version,
        name="demo chain",
        entry_point_arn=FLOW,
        discovered_at=NOW,
        nodes=built,
        edges=[],
        content_sha256="a" * 64,
        confirmed_by="operator-1",
        confirmed_at=NOW,
    )


class FakeDynamoDb:
    """Items keyed by (workflow_id, version), with a page size so scans must paginate."""

    def __init__(self, *, page_size: int = 1, fail_condition: bool = False, eventual: bool = False):
        self.items: dict[tuple[str, str], dict] = {}
        self.page_size = page_size
        self.fail_condition = fail_condition
        # Eventually consistent reads that lag the last write: a GetItem misses it and a Query
        # sees the version before it, unless the read asks for ConsistentRead.
        self.eventual = eventual
        self.calls: list[tuple[str, dict]] = []
        self.last_written: tuple[str, str] | None = None

    def put_item(self, **kwargs):
        self.calls.append(("put_item", kwargs))
        key = (kwargs["Item"]["workflow_id"]["S"], kwargs["Item"]["version"]["N"])
        if self.fail_condition or (key in self.items and "ConditionExpression" in kwargs):
            raise ClientError(
                {"Error": {"Code": "ConditionalCheckFailedException", "Message": "exists"}},
                "PutItem",
            )
        self.items[key] = kwargs["Item"]
        self.last_written = key
        return {}

    def lagging(self, kwargs) -> bool:
        return self.eventual and not kwargs.get("ConsistentRead")

    def get_item(self, **kwargs):
        self.calls.append(("get_item", kwargs))
        key = (kwargs["Key"]["workflow_id"]["S"], kwargs["Key"]["version"]["N"])
        item = None if self.lagging(kwargs) and key == self.last_written else self.items.get(key)
        return {"Item": item} if item else {}

    def query(self, **kwargs):
        self.calls.append(("query", kwargs))
        wanted = kwargs["ExpressionAttributeValues"][":id"]["S"]
        found = [
            item
            for key, item in self.items.items()
            if key[0] == wanted and not (self.lagging(kwargs) and key == self.last_written)
        ]
        descending = not kwargs["ScanIndexForward"]
        found.sort(key=lambda item: int(item["version"]["N"]), reverse=descending)
        return {"Items": found[: kwargs.get("Limit", len(found))]}

    def scan(self, **kwargs):
        self.calls.append(("scan", kwargs))
        ordered = list(self.items.values())
        start = 0
        if "ExclusiveStartKey" in kwargs:
            key = kwargs["ExclusiveStartKey"]
            start = next(
                index + 1
                for index, item in enumerate(ordered)
                if (item["workflow_id"], item["version"]) == (key["workflow_id"], key["version"])
            )
        page = ordered[start : start + self.page_size]
        projected_names = set(kwargs["ExpressionAttributeNames"].values())
        projected = [
            {name: value for name, value in item.items() if name in projected_names}
            for item in page
        ]
        answer = {"Items": projected}
        if start + self.page_size < len(ordered):
            last = page[-1]
            answer["LastEvaluatedKey"] = {
                "workflow_id": last["workflow_id"],
                "version": last["version"],
            }
        return answer


def store(dynamodb: FakeDynamoDb) -> DynamoDbWorkflowStore:
    return DynamoDbWorkflowStore(dynamodb, TABLE)


def test_a_save_is_conditional_and_reads_the_version_back():
    dynamodb = FakeDynamoDb()

    stored = store(dynamodb).save(workflow())

    [(_, put)] = [call for call in dynamodb.calls if call[0] == "put_item"]
    assert put["ConditionExpression"] == "attribute_not_exists(#v)"
    assert put["ExpressionAttributeNames"] == {"#v": "version"}  # `version` is reserved
    assert put["TableName"] == TABLE
    assert stored.content_sha256 == "a" * 64 and stored.version == 1


def test_a_version_that_exists_raises_version_already_exists():
    dynamodb = FakeDynamoDb()
    store(dynamodb).save(workflow())

    with pytest.raises(VersionAlreadyExists):
        store(dynamodb).save(workflow())


def test_another_dynamodb_error_is_classified_not_swallowed():
    dynamodb = FakeDynamoDb()

    def refuse(**_):
        raise ClientError({"Error": {"Code": "AccessDeniedException", "Message": "no"}}, "PutItem")

    dynamodb.put_item = refuse
    with pytest.raises(ToolFailure) as failure:
        store(dynamodb).save(workflow())
    assert failure.value.kind is FailureKind.PERMISSION_DENIED


def test_an_item_over_the_size_limit_is_refused_before_the_write():
    dynamodb = FakeDynamoDb()
    huge = workflow(nodes=4000)
    assert len(huge.model_dump_json().encode()) > MAX_ITEM_BYTES

    with pytest.raises(ToolFailure) as failure:
        store(dynamodb).save(huge)

    assert failure.value.kind is FailureKind.INVALID_REQUEST
    assert dynamodb.calls == []  # nothing reached DynamoDB


def test_the_latest_version_is_one_descending_query_limited_to_one():
    dynamodb = FakeDynamoDb()
    store(dynamodb).save(workflow(version=1))
    store(dynamodb).save(workflow(version=2))

    latest = store(dynamodb).read("demo-chain-ab12cd")

    assert latest is not None and latest.version == 2
    [(_, query)] = [call for call in dynamodb.calls if call[0] == "query"]
    assert query["ScanIndexForward"] is False and query["Limit"] == 1
    assert query["ExpressionAttributeNames"] == {"#w": "workflow_id"}


def test_one_version_is_read_by_get_item_and_an_absent_one_is_none():
    dynamodb = FakeDynamoDb()
    store(dynamodb).save(workflow(version=1))

    assert store(dynamodb).read("demo-chain-ab12cd", 1).version == 1
    assert store(dynamodb).read("demo-chain-ab12cd", 7) is None
    assert store(dynamodb).read("no-such-workflow", 1) is None


def test_summaries_follow_every_scan_page_and_keep_the_highest_version():
    dynamodb = FakeDynamoDb(page_size=1)
    for version in (1, 2, 3):
        store(dynamodb).save(workflow(version=version))
    store(dynamodb).save(workflow(version=1, workflow_id="another-chain-zz99"))

    summaries = store(dynamodb).summaries()

    assert [(item.workflow_id, item.latest_version) for item in summaries] == [
        ("another-chain-zz99", 1),
        ("demo-chain-ab12cd", 3),
    ]
    assert len([call for call in dynamodb.calls if call[0] == "scan"]) == 4  # paged to the end
    assert all(item.node_count == 2 for item in summaries)


def test_every_scanned_attribute_is_named_through_an_alias():
    dynamodb = FakeDynamoDb()
    store(dynamodb).save(workflow())

    store(dynamodb).summaries()

    [(_, scan)] = [call for call in dynamodb.calls if call[0] == "scan"]
    assert set(scan["ExpressionAttributeNames"]) == set(scan["ProjectionExpression"].split(", "))
    assert "name" in scan["ExpressionAttributeNames"].values()  # reserved word, aliased
    assert all(alias.startswith("#") for alias in scan["ExpressionAttributeNames"])


def test_the_stored_item_holds_a_never_empty_arn_set_for_contains_arn():
    item = build_item(workflow(nodes=0))

    assert item["node_arns"]["SS"] == [FLOW]  # the entry point is always there
    assert item["node_count"]["N"] == "0"


def test_contains_arn_is_one_paged_scan_over_the_latest_versions():
    """The scan projects node_arns, so matching needs no read per workflow."""
    dynamodb = FakeDynamoDb(page_size=1)
    store(dynamodb).save(workflow(version=1, nodes=2))
    store(dynamodb).save(workflow(version=2, nodes=1))  # the latest drops CHANNEL + "1"
    store(dynamodb).save(workflow(version=1, nodes=2, workflow_id="another-chain-zz99"))
    dynamodb.calls.clear()

    found = list_workflows(store(dynamodb), contains_arn=f"{CHANNEL}1")

    assert [summary.workflow_id for summary in found] == ["another-chain-zz99"]
    assert {name for name, _ in dynamodb.calls} == {"scan"}  # no Query or GetItem per workflow
    [first, *_] = [kwargs for name, kwargs in dynamodb.calls if name == "scan"]
    assert "node_arns" in first["ExpressionAttributeNames"].values()


def test_the_entry_point_always_matches_its_own_workflow():
    dynamodb = FakeDynamoDb()
    store(dynamodb).save(workflow(nodes=0))

    assert [s.workflow_id for s in list_workflows(store(dynamodb), contains_arn=FLOW)] == [
        "demo-chain-ab12cd"
    ]


def test_a_latest_item_whose_record_names_another_version_is_refused():
    """The Query picks the item by its sort key; the record inside must agree with it."""
    dynamodb = FakeDynamoDb()
    store(dynamodb).save(workflow(version=1))
    item = dynamodb.items[("demo-chain-ab12cd", "1")]
    item["version"] = {"N": "2"}  # the key says 2, the stored record still says 1
    dynamodb.items = {("demo-chain-ab12cd", "2"): item}

    assert store(dynamodb).read("demo-chain-ab12cd") is None


# --- A save is verified only by what was read back ---------------------------------------


def test_every_read_behind_a_save_is_strongly_consistent():
    dynamodb = FakeDynamoDb()
    store(dynamodb).save(workflow(version=1))
    store(dynamodb).read("demo-chain-ab12cd")

    reads = [kwargs for name, kwargs in dynamodb.calls if name in ("get_item", "query")]
    assert reads and all(kwargs.get("ConsistentRead") is True for kwargs in reads)


def test_a_lagging_table_still_reads_back_the_version_just_written():
    dynamodb = FakeDynamoDb(eventual=True)
    store(dynamodb).save(workflow(version=1))

    stored = store(dynamodb).save(workflow(version=2))

    assert stored is not None and stored.version == 2
    assert store(dynamodb).read("demo-chain-ab12cd").version == 2  # not the stale v1


def test_an_empty_read_back_is_reported_as_nothing_read_never_as_the_input():
    dynamodb = FakeDynamoDb()
    dynamodb.get_item = lambda **_: {}  # the write succeeded; the read-back found no item

    assert store(dynamodb).save(workflow()) is None


def test_a_save_whose_read_back_is_empty_is_not_verified():
    dynamodb = FakeDynamoDb()
    workflow_store = store(dynamodb)
    proposal = discover(replay("workflow_discovery"), workflow_store)
    dynamodb.get_item = lambda **_: {}

    result = save(workflow_store, proposal, approval_for(proposal))

    assert result.verified is False
    assert result.before_state == "absent"
    assert result.after_state == "v1 not read back: the store returned no item"
