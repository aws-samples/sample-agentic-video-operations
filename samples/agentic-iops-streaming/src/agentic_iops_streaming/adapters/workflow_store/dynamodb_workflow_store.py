"""The deployed workflow store: one DynamoDB table in this stack (§8.4).

`name` and `source` are DynamoDB reserved words, so every expression names attributes through
`ExpressionAttributeNames`, never literally. A save is conditional on the version not
existing, which is what makes stored versions immutable.

Every read is strongly consistent: an eventually consistent read just after a save can miss
the version it wrote, or report the one before it, and a save is verified only by its
read-back.
"""

from typing import Any

from botocore.exceptions import ClientError

from agentic_iops_streaming.domain.workflow_records import Workflow, WorkflowSummary
from agentic_iops_streaming.domain.workflow_store import (
    VersionAlreadyExists,
    keyed,
    refuse_oversize,
    sort_summaries,
)
from media_ops_contracts.call_aws_operation import call_aws_operation
from media_ops_contracts.classify_aws_error import classify_aws_error

WORKFLOW_ID = "#w"
VERSION = "#v"
# Every attribute is named through an alias: `name` and `source` are reserved words, and the
# rest follow the same rule so no expression has to know which names are reserved.
SUMMARY_ATTRIBUTES = {
    WORKFLOW_ID: "workflow_id",
    VERSION: "version",
    "#n": "name",
    "#e": "entry_point_arn",
    "#c": "confirmed_at",
    "#k": "node_count",
    "#a": "node_arns",
}
SUMMARY_PROJECTION = ", ".join(SUMMARY_ATTRIBUTES)


class DynamoDbWorkflowStore:
    """The workflow store over one table; every item holds the Workflow as JSON plus its keys."""

    def __init__(self, dynamodb: Any, table_name: str) -> None:
        self.dynamodb = dynamodb
        self.table_name = table_name

    def save(self, workflow: Workflow) -> Workflow | None:
        refuse_oversize(workflow)
        try:
            self.dynamodb.put_item(
                TableName=self.table_name,
                Item=build_item(workflow),
                ConditionExpression=f"attribute_not_exists({VERSION})",
                ExpressionAttributeNames={VERSION: "version"},
            )
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise VersionAlreadyExists(workflow.workflow_id) from error
            raise classify_aws_error(error, operation="put_item") from error
        return self.read(workflow.workflow_id, workflow.version)  # None: nothing read back

    def read(self, workflow_id: str, version: int | None = None) -> Workflow | None:
        if version is not None:
            answer = call_aws_operation(
                self.dynamodb,
                "get_item",
                TableName=self.table_name,
                Key={"workflow_id": {"S": workflow_id}, "version": {"N": str(version)}},
                ConsistentRead=True,
            )
            return keyed(read_workflow(answer.get("Item")), workflow_id, version)
        answer = call_aws_operation(
            self.dynamodb,
            "query",
            TableName=self.table_name,
            KeyConditionExpression=f"{WORKFLOW_ID} = :id",
            ExpressionAttributeNames={WORKFLOW_ID: "workflow_id"},
            ExpressionAttributeValues={":id": {"S": workflow_id}},
            ScanIndexForward=False,
            Limit=1,
            ConsistentRead=True,
        )
        items = answer.get("Items") or []
        if not items:
            return None
        # The Query picked this item by its sort key: the record inside must agree with it.
        return keyed(read_workflow(items[0]), workflow_id, int(items[0]["version"]["N"]))

    def summaries(self, contains_arn: str | None = None) -> list[WorkflowSummary]:
        highest: dict[str, tuple[WorkflowSummary, list[str]]] = {}
        for item in self.scan_every_page():
            summary = read_summary(item)
            kept = highest.get(summary.workflow_id)
            if kept is None or summary.latest_version > kept[0].latest_version:
                highest[summary.workflow_id] = (summary, item.get("node_arns", {}).get("SS", []))
        return sort_summaries(
            [
                summary
                for summary, node_arns in highest.values()
                if contains_arn is None
                or contains_arn in node_arns
                or contains_arn == summary.entry_point_arn
            ]
        )

    def scan_every_page(self) -> list[dict[str, Any]]:
        """Follow LastEvaluatedKey to the end: a partial scan would hide a workflow."""
        items: list[dict[str, Any]] = []
        start_key: dict[str, Any] | None = None
        while True:
            parameters: dict[str, Any] = {
                "TableName": self.table_name,
                "ProjectionExpression": SUMMARY_PROJECTION,
                "ExpressionAttributeNames": dict(SUMMARY_ATTRIBUTES),
            }
            if start_key:
                parameters["ExclusiveStartKey"] = start_key
            answer = call_aws_operation(self.dynamodb, "scan", **parameters)
            items.extend(answer.get("Items") or [])
            start_key = answer.get("LastEvaluatedKey")
            if not start_key:
                return items


def build_item(workflow: Workflow) -> dict[str, Any]:
    """The keys and the summary attributes as their own fields, the record as one JSON document."""
    return {
        "workflow_id": {"S": workflow.workflow_id},
        "version": {"N": str(workflow.version)},
        "name": {"S": workflow.name},
        "entry_point_arn": {"S": workflow.entry_point_arn},
        "confirmed_at": {"S": workflow.confirmed_at.isoformat()},
        "confirmed_by": {"S": workflow.confirmed_by},
        "content_sha256": {"S": workflow.content_sha256},
        "node_count": {"N": str(len(workflow.nodes))},
        "node_arns": {"SS": node_arns_of(workflow)},
        "document": {"S": workflow.model_dump_json()},
    }


def node_arns_of(workflow: Workflow) -> list[str]:
    """Never empty: DynamoDB rejects an empty string set, and the entry point is always a node."""
    arns = sorted({*workflow.node_arns, workflow.entry_point_arn})
    return [arn for arn in arns if arn]


def read_workflow(item: dict[str, Any] | None) -> Workflow | None:
    if not item:
        return None
    return Workflow.model_validate_json(item["document"]["S"])


def read_summary(item: dict[str, Any]) -> WorkflowSummary:
    """A projected item carries the summary fields; the document isn't read for a listing."""
    return WorkflowSummary(
        workflow_id=item["workflow_id"]["S"],
        name=item["name"]["S"],
        entry_point_arn=item["entry_point_arn"]["S"],
        latest_version=int(item["version"]["N"]),
        node_count=int(item["node_count"]["N"]),
        confirmed_at=item["confirmed_at"]["S"],
    )
