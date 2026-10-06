"""Deploy or destroy the Hydrolix AgentCore backend.

uv run python scripts/manage_hydrolix_stack.py deploy [--yes]
uv run python scripts/manage_hydrolix_stack.py destroy [--yes]
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from confirm_aws_action import NO_CREDENTIALS_FIX, ConfirmationPrompt, ask_to_continue

STACK = "CdkHydrolixDataAssistantAgentcoreStrandsStack"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CDK_DIRECTORY = (
    REPOSITORY_ROOT / "samples" / "hydrolix" / "cdk-hydrolix-data-assistant-agentcore-strands"
)
AGENT_DIRECTORY = CDK_DIRECTORY / "hydrolix-data-assistant-agentcore-strands"
MCP_DESTINATION = AGENT_DIRECTORY / "src" / "mcp" / "mcp_hydrolix"
MCP_REPOSITORY = "https://github.com/hydrolix/mcp-hydrolix.git"
MCP_COMMIT = "21eb1fe0b39028c2e91957086138bba9bc84bc1d"
CDK_EXECUTABLE = CDK_DIRECTORY / "node_modules" / ".bin" / "cdk"

Runner = Callable[[Sequence[str], Path | None, bool], subprocess.CompletedProcess[str]]


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


def read_required_settings(environ: Mapping[str, str]) -> dict[str, str] | None:
    names = ("AWS_REGION", "AGENT_MODEL_ID", "HYDROLIX_TABLE")
    values = {name: environ.get(name, "").strip() for name in names}
    missing = [name for name, value in values.items() if not value]
    if missing:
        print(f"Missing required setting(s): {', '.join(missing)}")
        print("Add them to the root .env, then re-run the command.")
        return None
    return values


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
        MCP_DESTINATION.parent.mkdir(parents=True, exist_ok=True)
        if MCP_DESTINATION.exists():
            shutil.rmtree(MCP_DESTINATION)
        shutil.copytree(source, MCP_DESTINATION)
    return 0


def install_cdk_dependencies(runner: Runner) -> int:
    result = runner(
        ["npm", "ci", "--no-audit", "--no-fund"],
        CDK_DIRECTORY,
        False,
    )
    return result.returncode


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
                f"BedrockModelId={settings['AGENT_MODEL_ID']}",
                "--parameters",
                f"HydrolixTable={settings['HYDROLIX_TABLE']}",
                "--require-approval",
                "never" if assume_yes else "broadening",
            ]
        )
    else:
        arguments.append("--force")
    return runner(arguments, CDK_DIRECTORY, False).returncode


def deploy_stack(
    runner: Runner,
    *,
    assume_yes: bool,
    environ: Mapping[str, str],
    ask: Callable[[str], str],
) -> int:
    settings = read_required_settings(environ)
    if settings is None:
        return 1
    account = read_account_id(runner, settings["AWS_REGION"])
    if account is None:
        print(NO_CREDENTIALS_FIX)
        return 1
    prompt = ConfirmationPrompt(
        "deploy (billable: AgentCore Runtime and Memory, DynamoDB, ECR, Secrets Manager)",
        STACK,
        settings["AWS_REGION"],
        account,
        {
            "Hydrolix table": settings["HYDROLIX_TABLE"],
            "Amplify app": "not created by this command",
        },
    )
    if not ask_to_continue(prompt, assume_yes=assume_yes, ask=ask):
        return 1
    for prepare in (install_pinned_mcp_server, install_cdk_dependencies):
        status = prepare(runner)
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
) -> int:
    region = environ.get("AWS_REGION", "").strip()
    if not region:
        print("Missing required setting(s): AWS_REGION")
        return 1
    account = read_account_id(runner, region)
    if account is None:
        print(NO_CREDENTIALS_FIX)
        return 1
    amplify_app_id = environ.get("HYDROLIX_AMPLIFY_APP_ID", "").strip()
    amplify_cleanup = amplify_app_id or "not managed; set HYDROLIX_AMPLIFY_APP_ID if created"
    prompt = ConfirmationPrompt(
        "destroy (deletes the backend and configured Amplify app)",
        STACK,
        region,
        account,
        {
            "Amplify app": amplify_cleanup,
            "Secrets Manager secret": "stack-generated Hydrolix credentials (deleted)",
        },
    )
    if not ask_to_continue(prompt, assume_yes=assume_yes, ask=ask):
        return 1
    if amplify_app_id:
        result = runner(
            ["aws", "amplify", "delete-app", "--region", region, "--app-id", amplify_app_id],
            REPOSITORY_ROOT,
            True,
        )
        missing = "NotFoundException" in f"{result.stdout}\n{result.stderr}"
        if result.returncode != 0 and not missing:
            print("Could not delete the configured Amplify app; backend teardown stopped.")
            return result.returncode
        if missing:
            print(f"Amplify app {amplify_app_id} is already absent; continuing teardown.")
    status = install_cdk_dependencies(runner)
    if status != 0:
        return status
    settings = {
        "AGENT_MODEL_ID": environ.get("AGENT_MODEL_ID", "unused-for-destroy"),
        "HYDROLIX_TABLE": environ.get("HYDROLIX_TABLE", "unused-for-destroy"),
    }
    status = run_cdk(runner, "destroy", settings, assume_yes=assume_yes)
    if status != 0:
        return status
    if MCP_DESTINATION.exists():
        shutil.rmtree(MCP_DESTINATION)
    print("Deleted the Hydrolix backend and its stack-owned Secrets Manager secret.")
    print("The CDK bootstrap ECR repository may retain the backend asset image.")
    if not amplify_app_id:
        print("No Amplify app was deleted because HYDROLIX_AMPLIFY_APP_ID was empty.")
    return 0


def main(
    argv: Sequence[str],
    runner: Runner = run_command,
    ask: Callable[[str], str] = input,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["deploy", "destroy"])
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    arguments = parser.parse_args(argv)
    if arguments.command == "deploy":
        return deploy_stack(runner, assume_yes=arguments.yes, environ=os.environ, ask=ask)
    return destroy_stack(runner, assume_yes=arguments.yes, environ=os.environ, ask=ask)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
