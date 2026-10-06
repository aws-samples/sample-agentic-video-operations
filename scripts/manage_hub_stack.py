"""Deploy or destroy the media ops hub (samples/hub/cdk) with the root .env settings.

uv run python scripts/manage_hub_stack.py deploy [--yes]
uv run python scripts/manage_hub_stack.py destroy [--yes]

MEDIA_DOMAINS selects the packs and their IAM; ALLOW_WRITES=true also grants the packs'
write permissions. Both are shown in the confirmation before anything is created.
"""

import argparse
import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from confirm_aws_action import NO_CREDENTIALS_FIX, ConfirmationPrompt, ask_to_continue
from read_aws_cli_error import describe_failure, is_missing_resource

STACK = "MediaOpsHubStack"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CDK_DIRECTORY = REPOSITORY_ROOT / "samples" / "hub" / "cdk"
CDK_EXECUTABLE = CDK_DIRECTORY / "node_modules" / ".bin" / "cdk"
# Must equal RUNTIME_NAME in samples/hub/cdk/lib/media-ops-hub-stack.ts. AgentCore runtime ids
# are `<name>-<suffix>`, so the trailing dash keeps similarly named runtimes' logs out.
RUNTIME_NAME = "MediaOpsHubRuntime"
RUNTIME_LOG_PREFIX = f"/aws/bedrock-agentcore/runtimes/{RUNTIME_NAME}-"
DEPLOY_ACTION = "deploy (billable: AgentCore Runtime and Memory, Bedrock, Secrets Manager)"
DESTROY_ACTION = "destroy (deletes everything listed below)"

Runner = Callable[[Sequence[str], Path | None, bool], subprocess.CompletedProcess[str]]


def run_command(
    arguments: Sequence[str], cwd: Path | None, capture: bool
) -> subprocess.CompletedProcess[str]:
    """Run one local command; no secret is ever an argument."""
    return subprocess.run(arguments, cwd=cwd, capture_output=capture, text=True, check=False)


def aws(runner: Runner, region: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return runner(["aws", *arguments, "--region", region], REPOSITORY_ROOT, True)


def read_account_id(runner: Runner, region: str) -> str | None:
    result = aws(
        runner, region, "sts", "get-caller-identity", "--query", "Account", "--output", "text"
    )
    value = result.stdout.strip() if result.returncode == 0 else ""
    return value if value and value != "None" else None


def read_deploy_settings(environ: Mapping[str, str]) -> dict[str, str] | None:
    settings = {
        "AWS_REGION": environ.get("AWS_REGION", "").strip(),
        "AGENT_MODEL_ID": environ.get("AGENT_MODEL_ID", "").strip(),
        "THUMBNAIL_MODEL_ID": environ.get("THUMBNAIL_MODEL_ID", "").strip(),
        "MEDIA_DOMAINS": environ.get("MEDIA_DOMAINS", "").strip() or "medialive,mediaconnect",
        "ALLOW_WRITES": "true" if environ.get("ALLOW_WRITES", "").lower() == "true" else "false",
        "HUB_INVOKER_ROLE_NAME": environ.get("HUB_INVOKER_ROLE_NAME", "").strip(),
    }
    missing = [name for name in ("AWS_REGION", "AGENT_MODEL_ID") if not settings[name]]
    if missing:
        print(f"Missing required setting(s): {', '.join(missing)}")
        print("Add them to the root .env (see .env.example), then re-run the command.")
        return None
    return settings


def install_cdk_dependencies(runner: Runner) -> int:
    return runner(["npm", "ci", "--no-audit", "--no-fund"], CDK_DIRECTORY, False).returncode


def deploy_stack(
    runner: Runner, *, assume_yes: bool, environ: Mapping[str, str], ask: Callable[[str], str]
) -> int:
    settings = read_deploy_settings(environ)
    if settings is None:
        return 1
    region = settings["AWS_REGION"]
    account = read_account_id(runner, region)
    if account is None:
        print(NO_CREDENTIALS_FIX)
        return 1
    details = {
        "domain packs": settings["MEDIA_DOMAINS"],
        "write tools and write IAM": "granted"
        if settings["ALLOW_WRITES"] == "true"
        else "not granted",  # fmt: skip
        "agent model": settings["AGENT_MODEL_ID"],
        "may invoke": settings["HUB_INVOKER_ROLE_NAME"] or "principals you grant InvokePolicyArn",
        "CDK bootstrap needed in": f"aws://{account}/{region} (cdk bootstrap, once)",
    }
    prompt = ConfirmationPrompt(DEPLOY_ACTION, STACK, region, account, details)
    if not ask_to_continue(prompt, assume_yes=assume_yes, ask=ask):
        return 1
    status = install_cdk_dependencies(runner)
    if status != 0:
        return status
    arguments = [
        str(CDK_EXECUTABLE), "deploy", STACK,
        "-c", f"mediaDomains={settings['MEDIA_DOMAINS']}",
        "-c", f"allowWrites={settings['ALLOW_WRITES']}",
        "--parameters", f"BedrockModelId={settings['AGENT_MODEL_ID']}",
        "--require-approval", "never" if assume_yes else "broadening",
    ]  # fmt: skip
    if settings["HUB_INVOKER_ROLE_NAME"]:
        arguments += ["-c", f"invokerRoleName={settings['HUB_INVOKER_ROLE_NAME']}"]
    if settings["THUMBNAIL_MODEL_ID"]:
        arguments += ["--parameters", f"ThumbnailModelId={settings['THUMBNAIL_MODEL_ID']}"]
    status = runner(arguments, CDK_DIRECTORY, False).returncode
    if status == 0:
        print("Deployed. Invoke it with the AgentRuntimeArn output; see samples/hub/README.md.")
    return status


def read_stack_presence(runner: Runner, region: str) -> bool | None:
    """True, False, or None when the lookup failed for another reason (fail closed)."""
    result = aws(
        runner, region, "cloudformation", "describe-stacks", "--stack-name", STACK,
        "--query", "Stacks[0].StackStatus", "--output", "text",
    )  # fmt: skip
    if result.returncode == 0:
        return True
    if is_missing_resource(result):
        return False
    print(f"Could not read stack {STACK}: {describe_failure(result)}")
    return None


def read_runtime_log_groups(runner: Runner, region: str) -> list[str] | None:
    result = aws(
        runner, region, "logs", "describe-log-groups",
        "--log-group-name-prefix", RUNTIME_LOG_PREFIX,
        "--query", "logGroups[].logGroupName", "--output", "text",
    )  # fmt: skip
    if result.returncode != 0:
        print(f"Could not list the hub's runtime log groups: {describe_failure(result)}")
        return None
    names = result.stdout.strip()
    return [] if names in ("", "None") else names.split()


def destroy_stack(
    runner: Runner, *, assume_yes: bool, environ: Mapping[str, str], ask: Callable[[str], str]
) -> int:
    region = environ.get("AWS_REGION", "").strip()
    if not region:
        print("Missing required setting: AWS_REGION. Add it to the root .env.")
        return 1
    account = read_account_id(runner, region)
    if account is None:
        print(NO_CREDENTIALS_FIX)
        return 1
    stack_exists = read_stack_presence(runner, region)
    log_groups = read_runtime_log_groups(runner, region)
    if stack_exists is None or log_groups is None:
        print("Nothing was deleted. Fix the error above, then re-run `just destroy hub`.")
        return 1
    if not stack_exists and not log_groups:
        print(f"Stack {STACK} and its runtime log groups are already absent.")
        return 0
    details = {
        "stack (runtime, endpoint, memory, signing-key secret, role)": STACK
        if stack_exists
        else "already absent",  # fmt: skip
        "runtime log groups": ", ".join(log_groups) or "none",
    }
    prompt = ConfirmationPrompt(DESTROY_ACTION, STACK, region, account, details)
    if not ask_to_continue(prompt, assume_yes=assume_yes, ask=ask):
        return 1
    remaining: list[str] = []
    if stack_exists:
        status = install_cdk_dependencies(runner)
        if status == 0:
            destroy = [str(CDK_EXECUTABLE), "destroy", STACK, "--force"]
            status = runner(destroy, CDK_DIRECTORY, False).returncode
        if status != 0:
            remaining.append(f"CloudFormation stack {STACK}")
    for name in log_groups:
        result = aws(runner, region, "logs", "delete-log-group", "--log-group-name", name)
        if result.returncode != 0 and not is_missing_resource(result):
            print(f"Could not delete log group {name}: {describe_failure(result)}")
            remaining.append(f"log group {name}")
    if remaining:
        print("Teardown incomplete. Remaining resources:")
        for resource in remaining:
            print(f"- {resource}")
        print("Fix the reported error(s), then re-run `just destroy hub`.")
        return 1
    print(
        f"Teardown complete: {STACK} and {len(log_groups)} runtime log group(s) are absent.\n"
        "The signing-key secret is scheduled for deletion by Secrets Manager (recovery window).\n"
        "The CDK bootstrap ECR repository may retain the hub image; remove it there if unused."
    )
    return 0


def main(
    argv: Sequence[str],
    runner: Runner = run_command,
    ask: Callable[[str], str] = input,
    environ: Mapping[str, str] = os.environ,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["deploy", "destroy"])
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    arguments = parser.parse_args(argv)
    action = deploy_stack if arguments.command == "deploy" else destroy_stack
    return action(runner, assume_yes=arguments.yes, environ=environ, ask=ask)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
