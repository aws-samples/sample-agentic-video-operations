"""Call one AWS operation and translate SDK errors into ToolFailure (write_safe_tools.md §2)."""

from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from media_ops_contracts.classify_aws_error import classify_aws_error


def call_aws_operation(client: Any, operation: str, **parameters: Any) -> Any:
    """Return `client.<operation>(**parameters)`; SDK errors become a classified ToolFailure."""
    try:
        return getattr(client, operation)(**parameters)
    except (BotoCoreError, ClientError) as error:
        raise classify_aws_error(error, operation=operation) from error


def collect_pages(client: Any, operation: str, item_key: str, **parameters: Any) -> list[Any]:
    """Follow NextToken through every page of `operation` and return all `item_key` items."""
    items: list[Any] = []
    next_token: str | None = None
    while True:
        page_parameters = {**parameters, **({"NextToken": next_token} if next_token else {})}
        page = call_aws_operation(client, operation, **page_parameters)
        items.extend(page.get(item_key, []))
        next_token = page.get("NextToken")
        if not next_token:
            return items
