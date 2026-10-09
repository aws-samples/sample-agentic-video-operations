"""Release gate: the default synth grants no write action and no `Resource: "*"` beyond need.

uv run python scripts/check_synth_iam.py
samples/agentic-iops-streaming/cdk/cdk.out/AgenticIopsStreamingStack.template.json

- A write is an action whose verb mutates (Create, Delete, Update, Put, Start, Stop, ...).
  Only the runtime's own telemetry and memory writes below are allowed, each with a reason,
  and each on its own resource where the API allows: an account-wide scope fails. Signal-map
  writes are allowed only on the app's own tagged maps.
- `Resource: "*"` is allowed only for the actions below, whose APIs have no resource-level
  permissions. Every other statement must name ARNs.
- NEVER_GRANT actions (workload identity tokens) fail on any resource; iam:PassRole and
  sts:AssumeRole fail on "*"; an action of "*" or "<service>:*" fails.
- Every statement must be readable, or it fails: a literal Effect of Allow or Deny,
  and literal action names. Policies are read wherever IAM keeps them (policy resources,
  and the inline policies of roles, users and groups), a managed policy may be attached
  only from this template, and a resource intrinsic that comes out as "*" counts as "*".
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
    "bedrock-agentcore:CreateEvent": "the agent's own session memory",
    "bedrock-agentcore:DeleteMemoryRecord": "the agent's own session memory",
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
TAG_SCOPED_WRITES = {
    "medialive:CreateSignalMap": ("aws:RequestTag/managed-by", True),
    "medialive:CreateTags": ("aws:RequestTag/managed-by", True),
    "medialive:DeleteSignalMap": ("aws:ResourceTag/managed-by", False),
}
MANAGED_BY_VALUE = "agentic-iops-streaming"
MANAGED_BY_TAG_KEYS = ["managed-by"]
SIGNAL_MAP_RESOURCE = {
    "Fn::Sub": ("arn:${AWS::Partition}:medialive:${AWS::Region}:${AWS::AccountId}:signal-map:*")
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
    tag_scoped_writes = {name.lower(): rule for name, rule in TAG_SCOPED_WRITES.items()}
    star_allowed = lowercase_keys(STAR_RESOURCE_ALLOWED)
    stack_resource_writes = lowercase_keys(STACK_RESOURCE_WRITES)
    problems = attachment_problems(template)
    for logical_id, statement in all_statements(template):
        unreadable = unreadable_statement(statement)
        if unreadable:
            problems.append(f"{logical_id}: {unreadable}")
            continue
        if statement["Effect"] != "Allow":
            continue  # a Deny only takes away
        if "NotAction" in statement or "NotResource" in statement:
            problems.append(f"{logical_id}: NotAction/NotResource is not allowed")
        actions = as_list(statement.get("Action"))
        resources = [literal(resource) for resource in as_list(statement.get("Resource"))]
        for action in actions:
            key = action.lower()
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
            elif (
                WRITE_VERB.match(verb)
                and key not in allowed_writes
                and key not in tag_scoped_writes
            ):
                problems.append(f"{logical_id}: write action {action} in the default synth")
            if "*" in resources and key not in star_allowed:
                problems.append(f'{logical_id}: {action} on Resource "*"')
            if key in allowed_writes:
                problems += account_wide_scopes(logical_id, action, resources)
            if key in tag_scoped_writes:
                problems += tag_scoped_write_problems(
                    logical_id,
                    action,
                    resources,
                    statement,
                    tag_scoped_writes[key],
                )
            if key in stack_resource_writes and (
                not resources
                or not all(
                    references_stack_resource(template, resource, stack_resource_writes[key])
                    for resource in resources
                )
            ):
                problems.append(
                    f"{logical_id}: {action} is not scoped to this stack's "
                    f"{stack_resource_writes[key]}"
                )
    return sorted(set(problems))


def tag_scoped_write_problems(
    logical_id: str,
    action: str,
    resources: list[Any],
    statement: dict[str, Any],
    rule: tuple[str, bool],
) -> list[str]:
    """Require the exact resource and tag condition for the app's signal-map writes."""
    condition_key, require_tag_keys = rule
    condition = statement.get("Condition")
    condition = condition if isinstance(condition, dict) else {}
    string_equals = condition.get("StringEquals")
    string_equals = string_equals if isinstance(string_equals, dict) else {}
    problems = []
    if string_equals.get(condition_key) != MANAGED_BY_VALUE:
        problems.append(
            f"{logical_id}: {action} requires StringEquals {condition_key}={MANAGED_BY_VALUE}"
        )
    if require_tag_keys:
        all_values = condition.get("ForAllValues:StringEquals")
        all_values = all_values if isinstance(all_values, dict) else {}
        if all_values.get("aws:TagKeys") != MANAGED_BY_TAG_KEYS:
            problems.append(
                f"{logical_id}: {action} requires ForAllValues:StringEquals "
                'aws:TagKeys=["managed-by"]'
            )
    if not resources or any(resource != SIGNAL_MAP_RESOURCE for resource in resources):
        problems.append(f"{logical_id}: {action} is not scoped to this stack's signal-map ARN")
    return problems


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


POLICY_RESOURCES = frozenset(
    {
        "AWS::IAM::Policy",
        "AWS::IAM::ManagedPolicy",
        "AWS::IAM::RolePolicy",
        "AWS::IAM::UserPolicy",
        "AWS::IAM::GroupPolicy",
    }
)
PRINCIPALS = frozenset({"AWS::IAM::Role", "AWS::IAM::User", "AWS::IAM::Group"})


def all_statements(template: dict[str, Any]) -> Iterable[tuple[str, Any]]:
    """Every statement of every identity policy, Allow or Deny, read or not."""
    for logical_id, resource in template.get("Resources", {}).items():
        properties = resource.get("Properties", {})
        documents = []
        if resource.get("Type") in POLICY_RESOURCES:
            documents.append(properties.get("PolicyDocument", {}))
        if resource.get("Type") in PRINCIPALS:
            documents += [p.get("PolicyDocument", {}) for p in properties.get("Policies", [])]
        for document in documents:
            statements = document.get("Statement") if isinstance(document, dict) else document
            for statement in as_list(statements):
                yield logical_id, statement


def unreadable_statement(statement: Any) -> str | None:
    """Why the gate can't judge this statement, or None. What it can't read, it refuses."""
    if not isinstance(statement, dict) or statement.keys() & {"Fn::If", "Ref"}:
        return "a statement chosen at deploy time (an intrinsic) can't be checked"
    if statement.get("Effect") not in ("Allow", "Deny"):
        return "a statement's Effect must be a literal Allow or Deny"
    actions = as_list(statement.get("Action")) + as_list(statement.get("NotAction"))
    if not all(isinstance(action, str) for action in actions):
        return "an Action built by an intrinsic can't be checked"
    return None


def attachment_problems(template: dict[str, Any]) -> list[str]:
    """A managed policy attached by ARN is one the gate never reads (AdministratorAccess)."""
    resources = template.get("Resources", {})
    problems = []
    for logical_id, resource in resources.items():
        if resource.get("Type") not in PRINCIPALS:
            continue
        for attached in as_list(resource.get("Properties", {}).get("ManagedPolicyArns")):
            reference = attached.get("Ref") if isinstance(attached, dict) else None
            if resources.get(reference, {}).get("Type") != "AWS::IAM::ManagedPolicy":
                problems.append(
                    f"{logical_id}: attaches a managed policy from outside this template "
                    f"({json.dumps(attached)})"
                )
    return problems


def literal(resource: Any) -> Any:
    """A resource intrinsic built only of literals, as the string it becomes; else as is."""
    if isinstance(resource, dict) and len(resource) == 1:
        [(function, argument)] = resource.items()
        if function == "Fn::Join" and isinstance(argument, list) and len(argument) == 2:
            separator, parts = argument
            if (
                isinstance(separator, str)
                and isinstance(parts, list)
                and all(isinstance(part, str) for part in parts)
            ):
                return separator.join(parts)
        if function == "Fn::Sub":
            text = argument[0] if isinstance(argument, list) and argument else argument
            if isinstance(text, str) and "${" not in text:
                return text
    return resource


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
