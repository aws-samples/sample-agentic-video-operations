"""Release gate: an AgentCore runtime is created only after its role's policies.

uv run python scripts/check_runtime_dependencies.py
samples/agentic-iops-streaming/cdk/cdk.out/*.template.json

AgentCore validates the execution role when it creates a runtime: it pulls the image from
ECR then and there. A runtime that only references its role (`RoleArn: GetAtt Role.Arn`)
can be created in the same second as a separate policy attached to that role, before the
ECR permissions exist, and the deploy fails and rolls back. So every AWS::IAM::Policy and
AWS::IAM::ManagedPolicy attached to a runtime's role must be in the runtime's DependsOn.
Inline policies on the role need nothing: they exist when the role does.

A role imported with `Role.fromRoleArn(..., {mutable: true})` gets the same race: grants
write an in-stack policy whose `Roles` holds the role's name, while the runtime holds its
ARN. Those are matched by role name, and a policy the template can't rule out is flagged.
"""

import json
import sys
from pathlib import Path
from typing import Any

RUNTIME = "AWS::BedrockAgentCore::Runtime"
ATTACHED_POLICIES = ("AWS::IAM::Policy", "AWS::IAM::ManagedPolicy")


def find_dependency_problems(template: dict[str, Any]) -> list[str]:
    resources = template.get("Resources", {})
    parameters = set(template.get("Parameters", {}))
    problems = []
    for runtime_id, runtime in resources.items():
        if runtime.get("Type") != RUNTIME:
            continue
        role = runtime_role(runtime.get("Properties", {}).get("RoleArn"), parameters)
        depends_on = set(as_list(runtime.get("DependsOn")))
        for policy_id, policy in resources.items():
            if policy.get("Type") not in ATTACHED_POLICIES or policy_id in depends_on:
                continue
            attached = {
                policy_role(entry, parameters)
                for entry in as_list(policy.get("Properties", {}).get("Roles"))
            }
            if role is not None and role in attached:
                problems.append(
                    f"{runtime_id} can be created before {policy_id}, a policy on its role "
                    f"{describe(role)}: add it to the runtime's DependsOn"
                )
            elif imported(role) and any(cannot_rule_out(role, entry) for entry in attached):
                problems.append(
                    f"{runtime_id} can be created before {policy_id}, which may be a policy on "
                    f"its imported role: add it to the runtime's DependsOn"
                )
    return problems


# A role is ("resource", logical id) for a role in this stack, ("name", role name) for an
# imported role named literally, ("parameter", parameter id) for an imported role whose name
# is a parameter, or None when the template doesn't say which role it is.
RoleKey = tuple[str, str] | None


def runtime_role(value: Any, parameters: set[str]) -> RoleKey:
    """The runtime's role, from `GetAtt Role.Arn`, `Ref Role`, a literal ARN, or the
    `Fn::Join`/`Fn::Sub` ARN that CDK writes for `Role.fromRoleArn` with a parameter."""
    if isinstance(value, str):
        return name_after_role(value)
    if not isinstance(value, dict):
        return None
    if "Fn::GetAtt" in value:
        target = value["Fn::GetAtt"]
        return ("resource", target[0] if isinstance(target, list) else str(target).split(".")[0])
    if "Ref" in value:
        return None if value["Ref"] in parameters else ("resource", str(value["Ref"]))
    if "Fn::Join" in value:
        delimiter, parts = value["Fn::Join"]
        if delimiter != "" or not isinstance(parts, list):
            return None
        for index, part in enumerate(parts):
            if isinstance(part, str) and ":role/" in part:
                tail = [part.split(":role/", 1)[1], *parts[index + 1 :]]
                tail = [piece for piece in tail if piece != ""]
                if len(tail) == 1 and isinstance(tail[0], str):
                    return name_after_role(":role/" + tail[0])
                if (
                    len(tail) == 1
                    and isinstance(tail[0], dict)
                    and tail[0].get("Ref") in parameters
                ):
                    return ("parameter", tail[0]["Ref"])
        return None
    if "Fn::Sub" in value and isinstance(value["Fn::Sub"], str):
        text = value["Fn::Sub"]
        if ":role/" not in text:
            return None
        role = text.split(":role/", 1)[1]
        if role.startswith("${") and role.endswith("}") and role[2:-1] in parameters:
            return ("parameter", role[2:-1])
        return name_after_role(text) if "${" not in role else None
    return None


def policy_role(value: Any, parameters: set[str]) -> RoleKey:
    """A `Roles` entry of a policy: a role name, `Ref Role`, `Ref Parameter` or `GetAtt`."""
    if isinstance(value, str):
        return ("name", value)
    if isinstance(value, dict) and "Ref" in value:
        kind = "parameter" if value["Ref"] in parameters else "resource"
        return (kind, str(value["Ref"]))
    if isinstance(value, dict) and "Fn::GetAtt" in value:
        target = value["Fn::GetAtt"]
        return ("resource", target[0] if isinstance(target, list) else str(target).split(".")[0])
    return None


def name_after_role(arn: str) -> RoleKey:
    if ":role/" not in arn:
        return None
    return ("name", arn.rsplit("/", 1)[1])  # policies name the role without its path


def imported(role: RoleKey) -> bool:
    return role is None or role[0] != "resource"


def cannot_rule_out(role: RoleKey, entry: RoleKey) -> bool:
    """Whether a policy entry might be the imported runtime role. A role created in this stack
    never is, nor is a different literal name. An entry the template doesn't name, a role
    named by a parameter, or any outside role when the runtime's own role is unknown might be.
    Fails closed: the fix is one DependsOn."""
    if entry is not None and entry[0] == "resource":
        return False
    if entry is None or role is None:
        return True
    return not (entry[0] == "name" and role[0] == "name")


def describe(role: tuple[str, str]) -> str:
    return f"named by parameter {role[1]}" if role[0] == "parameter" else role[1]


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def main(paths: list[str]) -> int:
    problems = [
        f"{path}: {problem}"
        for path in paths
        for problem in find_dependency_problems(json.loads(Path(path).read_text()))
    ]
    for problem in problems:
        print(problem)
    print("Runtime dependency checks passed." if not problems else f"{len(problems)} problem(s).")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
