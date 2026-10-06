"""Release gate: the default synth grants no write action and no `Resource: "*"` beyond need.

uv run python scripts/check_synth_iam.py samples/hub/cdk/cdk.out/MediaOpsHubStack.template.json

- A write is an action whose verb mutates (Create, Delete, Update, Put, Start, Stop, ...).
  Only the runtime's own telemetry and memory writes below are allowed, each with a reason,
  and each on its own resource where the API allows: an account-wide scope fails.
- `Resource: "*"` is allowed only for the actions below, whose APIs have no resource-level
  permissions. Every other statement must name ARNs.
- NEVER_GRANT actions (workload identity tokens) fail on any resource; iam:PassRole and
  sts:AssumeRole fail on "*"; an action of "*" or "<service>:*" fails.
"""

import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

WRITE_VERB = re.compile(  # BatchGet*/BatchCheck* (for example ECR pulls) are reads
    r"(?i)^(?!BatchGet|BatchCheck)(Create|Delete|Update|Put|Start|Stop|Batch|Modify|Tag|Untag|Attach|Detach|Associate|"
    r"Disassociate|Reboot|Terminate|Run|Send|Upload|Initiate|Complete|Set|Add|Remove|Restore)"
)
ALLOWED_WRITES = {
    "logs:CreateLogGroup": "the runtime's own log group",
    "logs:CreateLogStream": "the runtime's own log streams",
    "logs:PutLogEvents": "the runtime's own log events",
    "xray:PutTraceSegments": "the runtime's traces",
    "xray:PutTelemetryRecords": "the runtime's traces",
    "cloudwatch:PutMetricData": "runtime metrics, conditioned on the bedrock-agentcore namespace",
    "bedrock-agentcore:CreateEvent": "the hub's own session memory",
    "bedrock-agentcore:DeleteMemoryRecord": "the hub's own session memory",
    "dynamodb:PutItem": "the app's own table",
    "dynamodb:UpdateItem": "the app's own table",
}
# Allowed writes whose API supports resource-level scoping: an account-wide scope fails.
ACCOUNT_WIDE_SCOPE = {
    "logs:": re.compile(r"log-group:(\*|/aws/bedrock-agentcore/runtimes/\*)"),
    "bedrock-agentcore:CreateEvent": re.compile(r"memory/\*"),
    "bedrock-agentcore:DeleteMemoryRecord": re.compile(r"memory/\*"),
}
STACK_RESOURCE_WRITES = {
    "dynamodb:PutItem": "AWS::DynamoDB::Table",
    "dynamodb:UpdateItem": "AWS::DynamoDB::Table",
}

# Never granted, whatever the verb or resource: caller-selectable identity tokens (ForUserId
# trusts a caller-supplied user id), and passing or assuming any role at all.
NEVER_GRANT = {
    "bedrock-agentcore:GetWorkloadAccessToken": "workload identity tokens are unused here",
    "bedrock-agentcore:GetWorkloadAccessTokenForJWT": "workload identity tokens are unused here",
    "bedrock-agentcore:GetWorkloadAccessTokenForUserId": "trusts a caller-supplied user id",
}
NEVER_ON_STAR = {
    "iam:PassRole": "passing any role in the account escalates privilege",
    "sts:AssumeRole": "assuming any role in the account escalates privilege",
}

STAR_RESOURCE_ALLOWED = {
    "xray:PutTraceSegments": "X-Ray has no resource-level permissions",
    "xray:PutTelemetryRecords": "X-Ray has no resource-level permissions",
    "xray:GetSamplingRules": "X-Ray has no resource-level permissions",
    "xray:GetSamplingTargets": "X-Ray has no resource-level permissions",
    "cloudwatch:PutMetricData": "no resource-level permissions",
    "cloudwatch:GetMetricData": "no resource-level permissions",
    "medialive:ListChannels": "list actions have no resource-level permissions",
    "mediaconnect:ListFlows": "list actions have no resource-level permissions",
    "ecr:GetAuthorizationToken": "no resource-level permissions",
}


def find_iam_problems(template: dict[str, Any]) -> list[str]:
    """IAM action names are case-insensitive, so every comparison is on the lowercased name."""
    never_grant = lowercase_keys(NEVER_GRANT)
    never_on_star = lowercase_keys(NEVER_ON_STAR)
    allowed_writes = lowercase_keys(ALLOWED_WRITES)
    star_allowed = lowercase_keys(STAR_RESOURCE_ALLOWED)
    problems = []
    for logical_id, statement in allow_statements(template):
        if "NotAction" in statement or "NotResource" in statement:
            problems.append(f"{logical_id}: NotAction/NotResource is not allowed")
        actions = as_list(statement.get("Action"))
        resources = as_list(statement.get("Resource"))
        for action in actions:
            key = str(action).lower()
            verb = key.split(":", 1)[-1]
            if key in never_grant:
                problems.append(f"{logical_id}: {action} is never granted ({never_grant[key]})")
                continue
            if key in never_on_star and "*" in resources:
                problems.append(f'{logical_id}: {action} on Resource "*" ({never_on_star[key]})')
                continue
            if key in ("*", "*:*") or verb == "*":
                problems.append(f"{logical_id}: {action} grants every action")
                continue
            if "*" in key or "?" in key:  # IAM action wildcards
                problems.append(f"{logical_id}: wildcard action {action}")
            elif WRITE_VERB.match(verb) and key not in allowed_writes:
                problems.append(f"{logical_id}: write action {action} in the default synth")
            if "*" in resources and key not in star_allowed:
                problems.append(f'{logical_id}: {action} on Resource "*"')
            if key in allowed_writes:
                problems += account_wide_scopes(logical_id, action, resources)
            if action in STACK_RESOURCE_WRITES and (
                not resources
                or not all(
                    references_stack_resource(template, resource, STACK_RESOURCE_WRITES[action])
                    for resource in resources
                )
            ):
                problems.append(
                    f"{logical_id}: {action} is not scoped to this stack's "
                    f"{STACK_RESOURCE_WRITES[action]}"
                )
    return sorted(set(problems))


def lowercase_keys(table: dict[str, str]) -> dict[str, str]:
    return {name.lower(): reason for name, reason in table.items()}


def account_wide_scopes(logical_id: str, action: str, resources: list[Any]) -> list[str]:
    """An allowed write must name the stack's own resource, not every one in the account."""
    for prefix, pattern in ACCOUNT_WIDE_SCOPE.items():
        if action.lower().startswith(prefix.lower()) and any(
            pattern.search(json.dumps(r)) for r in resources
        ):
            return [f"{logical_id}: {action} is scoped account-wide, not to this stack's resource"]
    return []


def references_stack_resource(template: dict[str, Any], resource: Any, resource_type: str) -> bool:
    """Return whether an ARN is obtained from a resource of the expected type in this template."""
    get_att = resource.get("Fn::GetAtt") if isinstance(resource, dict) else None
    if not isinstance(get_att, list) or len(get_att) != 2 or get_att[1] != "Arn":
        return False
    logical_id = get_att[0]
    return template.get("Resources", {}).get(logical_id, {}).get("Type") == resource_type


def allow_statements(template: dict[str, Any]) -> Iterable[tuple[str, dict[str, Any]]]:
    for logical_id, resource in template.get("Resources", {}).items():
        properties = resource.get("Properties", {})
        documents = []
        if resource.get("Type") in ("AWS::IAM::Policy", "AWS::IAM::ManagedPolicy"):
            documents.append(properties.get("PolicyDocument", {}))
        if resource.get("Type") == "AWS::IAM::Role":
            documents += [p.get("PolicyDocument", {}) for p in properties.get("Policies", [])]
        for document in documents:
            for statement in as_list(document.get("Statement")):
                if statement.get("Effect") == "Allow":
                    yield logical_id, statement


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [] if value is None else [value]


def main(paths: list[str]) -> int:
    problems = [
        f"{path}: {problem}"
        for path in paths
        for problem in find_iam_problems(json.loads(Path(path).read_text()))
    ]
    for problem in problems:
        print(problem)
    print("IAM checks passed." if not problems else f"{len(problems)} IAM problem(s).")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
