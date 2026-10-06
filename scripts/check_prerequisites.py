"""`just doctor`: check what the samples need before the first run or deploy.

Every failed check prints the one command that fixes it. Exit code 1 if any check fails.
"""

import os
import re
import shutil
import subprocess
from dataclasses import dataclass

DEFAULT_AGENT_MODEL_ID = "us.anthropic.claude-sonnet-4-6"
DEFAULT_THUMBNAIL_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
MINIMUM_NODE_MAJOR = 20


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str
    fix: str = ""


def run_command(*command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)


def check_tool(name: str, fix: str) -> CheckResult:
    path = shutil.which(name)
    return CheckResult(name, path is not None, path or "not found", fix)


def check_docker() -> CheckResult:
    if not shutil.which("docker"):
        return CheckResult("docker", False, "not found", "Install Docker Desktop or Finch")
    running = run_command("docker", "info").returncode == 0
    return CheckResult(
        "docker daemon", running, "running" if running else "not running", "Start Docker Desktop"
    )


def check_node() -> CheckResult:
    if not shutil.which("node"):
        return CheckResult("node", False, "not found", "brew install node")
    version = run_command("node", "--version").stdout.strip()
    major = int(re.match(r"v(\d+)", version).group(1)) if version.startswith("v") else 0
    return CheckResult(
        "node",
        major >= MINIMUM_NODE_MAJOR,
        version,
        f"Install Node.js {MINIMUM_NODE_MAJOR} or newer",
    )


def check_aws_credentials() -> CheckResult:
    result = run_command(
        "aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text"
    )
    passed = result.returncode == 0
    detail = f"account {result.stdout.strip()}" if passed else "no valid credentials"
    return CheckResult(
        "aws credentials", passed, detail, "aws configure sso  # or export AWS_PROFILE"
    )


def check_region() -> CheckResult:
    region = os.environ.get("AWS_REGION", "")
    return CheckResult(
        "AWS_REGION",
        bool(region),
        region or "not set",
        "cp .env.example .env  # then set AWS_REGION",
    )


def check_model_access(variable: str, default: str, region: str) -> CheckResult:
    model_id = os.environ.get(variable, default)
    if re.match(r"^(us|eu|apac|global)\.", model_id):
        command = (
            "aws",
            "bedrock",
            "get-inference-profile",
            "--inference-profile-identifier",
            model_id,
        )
    else:
        command = ("aws", "bedrock", "get-foundation-model", "--model-identifier", model_id)
    passed = run_command(*command, "--region", region).returncode == 0
    return CheckResult(
        variable,
        passed,
        model_id,
        f"Enable {model_id} in the Bedrock console for {region}, or change {variable}",
    )


def check_cdk_bootstrap(region: str) -> CheckResult:
    result = run_command(
        "aws", "cloudformation", "describe-stacks", "--stack-name", "CDKToolkit", "--region", region
    )
    passed = result.returncode == 0
    return CheckResult(
        "cdk bootstrap",
        passed,
        "CDKToolkit found" if passed else "missing",
        f"npx cdk bootstrap aws://<account>/{region}",
    )


def collect_results() -> list[CheckResult]:
    results = [
        check_tool("uv", "curl -LsSf https://astral.sh/uv/install.sh | sh"),
        check_tool("just", "uv tool install rust-just"),
        check_tool("aws", "brew install awscli"),
        check_node(),
        check_docker(),
        check_region(),
    ]
    region = os.environ.get("AWS_REGION", "")
    if not (shutil.which("aws") and region):
        return results
    credentials = check_aws_credentials()
    results.append(credentials)
    if credentials.passed:
        results.append(check_model_access("AGENT_MODEL_ID", DEFAULT_AGENT_MODEL_ID, region))
        results.append(check_model_access("THUMBNAIL_MODEL_ID", DEFAULT_THUMBNAIL_MODEL_ID, region))
        results.append(check_cdk_bootstrap(region))
    return results


def main() -> int:
    results = collect_results()
    for result in results:
        mark = "ok  " if result.passed else "FAIL"
        print(f"{mark} {result.name:<20} {result.detail}")
        if not result.passed:
            print(f"     fix: {result.fix}")
    failed = [result for result in results if not result.passed]
    print("\nAll checks passed." if not failed else f"\n{len(failed)} check(s) failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
