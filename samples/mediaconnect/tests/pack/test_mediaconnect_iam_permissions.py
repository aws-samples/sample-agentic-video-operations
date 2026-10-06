"""Keep the MediaConnect pack IAM declaration aligned with adapter calls."""

import ast
import json
from pathlib import Path

SAMPLE = Path(__file__).resolve().parents[2]
SERVICE_BY_CLIENT = {
    "media_connect": "mediaconnect",
    "cloudwatch": "cloudwatch",
    "bedrock": "bedrock",
}
IAM_ACTION_OVERRIDES = {"bedrock:Converse": "bedrock:InvokeModel"}
Permissions = dict[str, list[dict[str, list[str]]]]


def adapter_operations() -> set[str]:
    actions = set()
    for path in (SAMPLE / "src/mediaconnect_mcp/adapters").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in SERVICE_BY_CLIENT
            ):
                continue
            service = SERVICE_BY_CLIENT[node.func.value.id]
            operation = node.func.attr
            if operation == "get_paginator":
                operation = node.args[0].value
            camel = "".join(part.capitalize() for part in operation.split("_"))
            action = f"{service}:{camel}"
            actions.add(IAM_ACTION_OVERRIDES.get(action, action))
    return actions


def load_permissions() -> Permissions:
    return json.loads((SAMPLE / "iam_permissions.json").read_text())


def test_permissions_cover_every_aws_operation_the_adapters_call():
    permissions = load_permissions()
    granted = {
        action
        for group in ("read", "write")
        for statement in permissions[group]
        for action in statement["actions"]
    }
    operations = adapter_operations()

    assert {"mediaconnect:StopFlow", "cloudwatch:GetMetricData"} <= operations
    assert operations <= granted, operations - granted


def test_write_permissions_are_only_the_write_operations():
    writes = {
        action for statement in load_permissions()["write"] for action in statement["actions"]
    }
    assert writes == {"mediaconnect:StartFlow", "mediaconnect:StopFlow"}


def test_flow_permissions_are_scoped_to_flow_resources():
    statements = [
        statement
        for group in ("read", "write")
        for statement in load_permissions()[group]
        if any(action.startswith("mediaconnect:") for action in statement["actions"])
        and statement["actions"] != ["mediaconnect:ListFlows"]
    ]
    assert statements
    assert all(
        statement["resources"] == ["arn:aws:mediaconnect:{region}:{account}:flow:*"]
        for statement in statements
    )
