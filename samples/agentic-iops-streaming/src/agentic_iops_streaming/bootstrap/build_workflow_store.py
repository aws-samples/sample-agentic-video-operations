"""Choose the workflow store this process writes to (§8.4).

Deployed, the CDK sets `WORKFLOW_TABLE_NAME` and the store is that one DynamoDB table. Locally
and in demo mode there is no table, so versions are JSON files under the ignored `.cache/`.
"""

from agentic_iops_streaming.adapters.workflow_store.dynamodb_workflow_store import (
    DynamoDbWorkflowStore,
)
from agentic_iops_streaming.adapters.workflow_store.local_workflow_store import LocalWorkflowStore
from agentic_iops_streaming.domain.workflow_store import WorkflowStore
from agentic_iops_streaming.settings.runtime_settings import AgenticIopsSettings
from media_ops_contracts.create_aws_client import create_aws_client


def build_workflow_store(settings: AgenticIopsSettings) -> WorkflowStore:
    if not settings.workflow_table_name:
        return LocalWorkflowStore(settings.workflow_dir)
    dynamodb = create_aws_client("dynamodb", region=settings.aws_region, demo=False)
    return DynamoDbWorkflowStore(dynamodb, settings.workflow_table_name)
