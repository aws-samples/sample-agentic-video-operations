"""Deploy or destroy the Hydrolix AgentCore backend.

uv run python scripts/manage_hydrolix_stack.py deploy [--yes]
uv run python scripts/manage_hydrolix_stack.py destroy [--yes]
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from check_cdk_deploy_plan import approval_line, check_cdk_bootstrap, show_security_diff
from confirm_aws_action import NO_CREDENTIALS_FIX, ConfirmationPrompt, ask_to_continue
from model_id_rule import find_invalid_model_ids
from read_root_env import describe_root_env, load_root_env

STACK = "CdkHydrolixDataAssistantAgentcoreStrandsStack"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CDK_DIRECTORY = (
    REPOSITORY_ROOT / "samples" / "hydrolix" / "cdk-hydrolix-data-assistant-agentcore-strands"
)
AGENT_DIRECTORY = CDK_DIRECTORY / "hydrolix-data-assistant-agentcore-strands"
MCP_DESTINATION = AGENT_DIRECTORY / "src" / "mcp" / "mcp_hydrolix"
MCP_REPOSITORY = "https://github.com/hydrolix/mcp-hydrolix.git"
MCP_COMMIT = "b18040434bd3c5bae3d770219279c6531415c760"  # v0.3.7
CDK_EXECUTABLE = CDK_DIRECTORY / "node_modules" / ".bin" / "cdk"

Runner = Callable[[Sequence[str], Path | None, bool], subprocess.CompletedProcess[str]]
MISSING_STACK = re.compile(r"Stack with id .+ does not exist")
MISSING_ERROR = re.compile(r"An error occurred \((NotFoundException|ResourceNotFoundException)\)")


@dataclass(frozen=True)
class StackResources:
    status: str
    secret_arn: str | None
    retired_table: str | None = None  # the pre-T41 results table, retained by design


@dataclass(frozen=True)
class AmplifyApp:
    app_id: str
    name: str


def run_command(
    arguments: Sequence[str], cwd: Path | None, capture: bool
) -> subprocess.CompletedProcess[str]:
    """Run one local command without adding secrets to its arguments."""
    return subprocess.run(
        arguments,
        cwd=cwd,
        capture_output=capture,
        text=True,
        check=False,
    )


def read_account_id(runner: Runner, region: str) -> str | None:
    result = runner(
        [
            "aws",
            "sts",
            "get-caller-identity",
            "--region",
            region,
            "--query",
            "Account",
            "--output",
            "text",
        ],
        REPOSITORY_ROOT,
        True,
    )
    value = result.stdout.strip() if result.returncode == 0 else ""
    return value if value and value != "None" else None


def is_missing(result: subprocess.CompletedProcess[str]) -> bool:
    message = f"{result.stdout}\n{result.stderr}"
    return bool(MISSING_STACK.search(message) or MISSING_ERROR.search(message))


def failure_detail(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout).strip() or f"command exited {result.returncode}"


def read_stack_resources(runner: Runner, region: str) -> StackResources | None:
    result = runner(
        [
            "aws", "cloudformation", "describe-stacks", "--region", region,
            "--stack-name", STACK, "--output", "json",
        ],
        REPOSITORY_ROOT,
        True,
    )  # fmt: skip
    if result.returncode != 0:
        if is_missing(result):
            return None
        raise RuntimeError(f"Could not read stack {STACK}: {failure_detail(result)}")
    stack = json.loads(result.stdout)["Stacks"][0]
    outputs = {item["OutputKey"]: item["OutputValue"] for item in stack.get("Outputs", [])}
    return StackResources(
        stack["StackStatus"],
        outputs.get("HydrolixSecretArn"),
        outputs.get("RetiredQueryResultsTableName"),
    )


def read_amplify_app(runner: Runner, region: str, app_id: str) -> AmplifyApp | None:
    if not app_id:
        return None
    result = runner(
        [
            "aws", "amplify", "get-app", "--region", region, "--app-id", app_id,
            "--output", "json",
        ],
        REPOSITORY_ROOT,
        True,
    )  # fmt: skip
    if result.returncode == 0:
        try:
            app = json.loads(result.stdout)["app"]
            returned_id = app["appId"].strip()
            name = app["name"].strip()
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            raise RuntimeError(f"Amplify returned incomplete details for app {app_id}.") from error
        if returned_id != app_id or not name:
            raise RuntimeError(f"Amplify returned incomplete details for app {app_id}.")
        return AmplifyApp(app_id=returned_id, name=name)
    if is_missing(result):
        return None
    raise RuntimeError(f"Could not read Amplify app {app_id}: {failure_detail(result)}")


def read_required_settings(environ: Mapping[str, str]) -> dict[str, str] | None:
    names = ("AWS_REGION", "AGENT_MODEL_ID", "HYDROLIX_TABLE")
    values = {name: environ.get(name, "").strip() for name in names}
    missing = [name for name, value in values.items() if not value]
    if missing:
        print(f"Missing required setting(s): {', '.join(missing)}")
        print(f"They are not set in the environment or in {describe_root_env()}.")
        print("Add them there, then re-run the command.")
        return None
    if invalid := find_invalid_model_ids(values, ("AGENT_MODEL_ID",)):
        print("\n".join(invalid))
        return None
    for name in ("HYDROLIX_JWT_DISCOVERY_URL", "HYDROLIX_JWT_CLIENT_IDS"):
        values[name] = environ.get(name, "").strip()
    if bool(values["HYDROLIX_JWT_DISCOVERY_URL"]) != bool(values["HYDROLIX_JWT_CLIENT_IDS"]):
        print("Set both HYDROLIX_JWT_DISCOVERY_URL and HYDROLIX_JWT_CLIENT_IDS, or neither.")
        return None
    return values


def describe_callers(settings: Mapping[str, str]) -> str:
    if settings.get("HYDROLIX_JWT_DISCOVERY_URL"):
        return (
            f"Cognito access tokens of app clients {settings['HYDROLIX_JWT_CLIENT_IDS']}; "
            "actor = token sub, memory per user"
        )
    return "IAM callers; no verified identity, so the agent runs with memory off"


def install_pinned_mcp_server(runner: Runner) -> int:
    """Install the exact reviewed mcp_hydrolix source into the Docker build context."""
    with tempfile.TemporaryDirectory(prefix="video-ops-mcp-hydrolix-") as temporary:
        checkout = Path(temporary) / "mcp-hydrolix"
        clone = runner(["git", "clone", "--quiet", MCP_REPOSITORY, str(checkout)], None, False)
        if clone.returncode != 0:
            return clone.returncode
        pin = runner(["git", "checkout", "--quiet", "--detach", MCP_COMMIT], checkout, False)
        if pin.returncode != 0:
            return pin.returncode
        source = checkout / "mcp_hydrolix"
        if not source.is_dir():
            print("Pinned mcp-hydrolix checkout does not contain mcp_hydrolix/.")
            return 1
        license_file = checkout / "LICENSE"
        if not license_file.is_file():
            print("Pinned mcp-hydrolix checkout does not contain LICENSE.")
            return 1
        MCP_DESTINATION.parent.mkdir(parents=True, exist_ok=True)
        if MCP_DESTINATION.exists():
            shutil.rmtree(MCP_DESTINATION)
        shutil.copytree(source, MCP_DESTINATION)
        shutil.copy2(license_file, MCP_DESTINATION / "LICENSE")
        notice_file = checkout / "NOTICE"
        if notice_file.is_file():
            shutil.copy2(notice_file, MCP_DESTINATION / "NOTICE")
    return 0


def install_cdk_dependencies(runner: Runner) -> int:
    result = runner(
        ["npm", "ci", "--no-audit", "--no-fund"],
        CDK_DIRECTORY,
        False,
    )
    return result.returncode


def cdk_context(settings: Mapping[str, str]) -> list[str]:
    """The -c options both the security diff and the deploy synthesize with. The model is
    context: it sets BedrockModelId's default, so both synthesize the same template (T71)."""
    context = ["-c", f"agentModelId={settings['AGENT_MODEL_ID']}"]
    if settings.get("HYDROLIX_JWT_DISCOVERY_URL"):
        context += [
            "-c", f"jwtDiscoveryUrl={settings['HYDROLIX_JWT_DISCOVERY_URL']}",
            "-c", f"jwtClientIds={settings['HYDROLIX_JWT_CLIENT_IDS']}",
        ]  # fmt: skip
    return context


def run_cdk(
    runner: Runner,
    action: str,
    settings: Mapping[str, str],
    *,
    assume_yes: bool,
) -> int:
    arguments = [str(CDK_EXECUTABLE), action, STACK]
    if action == "deploy":
        arguments.extend(
            [
                "--parameters",
                f"HydrolixTable={settings['HYDROLIX_TABLE']}",
                # BedrockModelId takes the default the context set, not the stack's last value.
                "--no-previous-parameters",
                "--require-approval",
                "never",  # approved by the repository's one confirmation, with the diff
            ]
        )
        arguments += cdk_context(settings)
    else:
        arguments.append("--force")
    return runner(arguments, CDK_DIRECTORY, False).returncode


def deploy_stack(
    runner: Runner,
    *,
    assume_yes: bool,
    environ: Mapping[str, str],
    ask: Callable[[str], str],
    interactive: bool = True,
) -> int:
    """One confirmation, after the bootstrap check and the security diff and before the MCP
    source is fetched or the image built: CDK then deploys with --require-approval never."""
    settings = read_required_settings(environ)
    if settings is None:
        return 1
    account = read_account_id(runner, settings["AWS_REGION"])
    if account is None:
        print(NO_CREDENTIALS_FIX)
        return 1
    bootstrap = check_cdk_bootstrap(runner, settings["AWS_REGION"], account, CDK_DIRECTORY)
    if bootstrap is None:
        return 1
    status = install_cdk_dependencies(runner)
    if status != 0:
        return status
    security = show_security_diff(
        runner, CDK_EXECUTABLE, STACK, cdk_context(settings), CDK_DIRECTORY
    )
    if security is None:
        return 1
    print(f"CDK bootstrap: {bootstrap}")
    prompt = ConfirmationPrompt(
        "deploy (billable: AgentCore Runtime and Memory, DynamoDB, ECR, Secrets Manager)",
        STACK,
        settings["AWS_REGION"],
        account,
        {
            "Hydrolix table": settings["HYDROLIX_TABLE"],
            # The security diff shows the grant as a Ref to BedrockModelId; this is its value.
            "Bedrock model granted": f"{settings['AGENT_MODEL_ID']} (its profile and model only)",
            "may invoke": describe_callers(settings),
            "Amplify app": "not created by this command",
            "CDK bootstrap": bootstrap,
            "security changes": security,
            "IAM approval": approval_line(assume_yes),
        },
    )
    if not ask_to_continue(prompt, assume_yes=assume_yes, ask=ask, interactive=interactive):
        return 1
    status = install_pinned_mcp_server(runner)
    if status != 0:
        return status
    status = run_cdk(runner, "deploy", settings, assume_yes=assume_yes)
    if status != 0:
        return status
    print(
        "\nBackend deployed. Update the stack-owned Hydrolix credentials secret without "
        "printing its value, then configure the Amplify app from the stack outputs."
    )
    print(
        "For an Amplify app created manually, set HYDROLIX_AMPLIFY_APP_ID in the root "
        ".env so `just destroy hydrolix` includes it."
    )
    return 0


def destroy_stack(
    runner: Runner,
    *,
    assume_yes: bool,
    environ: Mapping[str, str],
    ask: Callable[[str], str],
    interactive: bool = True,
) -> int:
    region = environ.get("AWS_REGION", "").strip()
    if not region:
        print("Missing required setting(s): AWS_REGION")
        return 1
    account = read_account_id(runner, region)
    if account is None:
        print(NO_CREDENTIALS_FIX)
        return 1
    configured_app = environ.get("HYDROLIX_AMPLIFY_APP_ID", "").strip()
    try:
        stack = read_stack_resources(runner, region)
    except RuntimeError as error:
        print(error)
        print("Nothing was deleted.")
        return 1
    try:
        amplify_app = read_amplify_app(runner, region, configured_app)
    except RuntimeError as error:
        print(error)
        print("Nothing was deleted.")
        return 1
    if stack is None and amplify_app is None:
        print(f"CloudFormation stack {STACK} and the configured Amplify app are already absent.")
        return 0
    prompt = ConfirmationPrompt(
        "destroy (deletes the backend and configured Amplify app)",
        STACK,
        region,
        account,
        {
            "CloudFormation stack": f"{STACK} ({stack.status})"
            if stack
            else "already absent",  # fmt: skip
            "Secrets Manager secret": (
                stack.secret_arn or "not present in stack outputs" if stack else "already absent"
            ),
            "Amplify app": (
                f"{amplify_app.name} ({amplify_app.app_id})" if amplify_app else "none found"
            ),
            **(
                {"Earlier results table": f"{stack.retired_table} (left in place by design)"}
                if stack and stack.retired_table
                else {}
            ),
        },
    )
    if not ask_to_continue(prompt, assume_yes=assume_yes, ask=ask, interactive=interactive):
        return 1
    amplify_failed = False
    if amplify_app:
        result = runner(
            ["aws", "amplify", "delete-app", "--region", region, "--app-id", amplify_app.app_id],
            REPOSITORY_ROOT,
            True,
        )
        if result.returncode != 0 and not is_missing(result):
            print(
                f"Could not delete Amplify app {amplify_app.name} "
                f"({amplify_app.app_id}): {failure_detail(result)}"
            )
            amplify_failed = True
        elif result.returncode != 0:
            print(
                f"Amplify app {amplify_app.name} ({amplify_app.app_id}) "
                "is already absent; continuing teardown."
            )
            amplify_app = None
        else:
            amplify_app = None
    stack_failed = False
    settings = {
        "AGENT_MODEL_ID": environ.get("AGENT_MODEL_ID", "unused-for-destroy"),
        "HYDROLIX_TABLE": environ.get("HYDROLIX_TABLE", "unused-for-destroy"),
    }
    if stack:
        install_status = install_cdk_dependencies(runner)
        stack_failed = install_status != 0
        if not stack_failed:
            stack_failed = run_cdk(runner, "destroy", settings, assume_yes=assume_yes) != 0
    if not stack_failed and MCP_DESTINATION.exists():
        shutil.rmtree(MCP_DESTINATION)
    if amplify_failed or stack_failed:
        print("Teardown incomplete. Remaining resources:")
        if stack_failed:
            print(f"- CloudFormation stack: {STACK}")
            if stack.secret_arn:
                print(f"- Secrets Manager secret: {stack.secret_arn}")
        if amplify_failed and amplify_app:
            print(f"- Amplify app: {amplify_app.name} ({amplify_app.app_id})")
        print("Fix the reported error(s), then re-run `just destroy hydrolix`.")
        return 1
    print("Teardown complete: the Hydrolix backend and configured Amplify app are absent.")
    if stack and stack.retired_table:
        # Printed, never run: only the operator decides when that history can go.
        print(
            f"The earlier results table {stack.retired_table} is left in place by design. "
            "Delete it when you no longer need its history:\n"
            f"  aws dynamodb delete-table --region {region} --table-name {stack.retired_table}"
        )
    print("The CDK bootstrap ECR repository may retain the backend asset image.")
    if not configured_app:
        print("No Amplify app was deleted because HYDROLIX_AMPLIFY_APP_ID was empty.")
    return 0


def main(
    argv: Sequence[str],
    runner: Runner = run_command,
    ask: Callable[[str], str] = input,
    interactive: bool | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["deploy", "destroy"])
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    arguments = parser.parse_args(argv)
    action = deploy_stack if arguments.command == "deploy" else destroy_stack
    terminal = sys.stdin.isatty() if interactive is None else interactive
    return action(
        runner, assume_yes=arguments.yes, environ=os.environ, ask=ask, interactive=terminal
    )


if __name__ == "__main__":
    load_root_env(os.environ)
    sys.exit(main(sys.argv[1:]))
