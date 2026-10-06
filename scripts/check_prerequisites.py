"""Check offline and AWS deployment prerequisites.

`just doctor` fails only when the offline development group is incomplete.
`just doctor aws` makes AWS and deployment checks strict too.
"""

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

MINIMUM_NODE_MAJOR = 20
# The probe bounds itself at 180 s (smoke_aws_servers.TIMEOUT_SECONDS); allow it to report.
AWS_PROBE_TIMEOUT_SECONDS = 190
MINIMUM_PYTHON = (3, 12)
SESSION_MANAGER_INSTALL = (
    "Install the Session Manager plugin: "
    "https://docs.aws.amazon.com/systems-manager/latest/userguide/"
    "session-manager-working-with-install-plugin.html"
)


class CheckGroup(StrEnum):
    OFFLINE = "offline"
    AWS = "aws"
    # Optional media tooling: reported, never required, never blocking.
    MEDIA = "media"


@dataclass(frozen=True)
class CheckResult:
    group: CheckGroup
    name: str
    passed: bool
    detail: str
    fix: str = ""


def run_command(*command: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(command, 124, "", "timed out")


def check_tool(name: str, fix: str, group: CheckGroup) -> CheckResult:
    path = shutil.which(name)
    return CheckResult(group, name, path is not None, path or "not found", fix)


def check_python_version() -> CheckResult:
    version = platform.python_version()
    return CheckResult(
        CheckGroup.OFFLINE,
        "python",
        sys.version_info >= MINIMUM_PYTHON,
        version,
        "uv python install 3.12",
    )


def check_docker() -> CheckResult:
    if not shutil.which("docker"):
        return CheckResult(
            CheckGroup.AWS,
            "docker",
            False,
            "not found",
            "Install Docker: https://docs.docker.com/get-docker/",
        )
    running = run_command("docker", "info").returncode == 0
    return CheckResult(
        CheckGroup.AWS,
        "docker daemon",
        running,
        "running" if running else "not running",
        "Start Docker Desktop, or start the Docker Engine service",
    )


def check_node() -> CheckResult:
    if not shutil.which("node"):
        return CheckResult(
            CheckGroup.AWS,
            "node",
            False,
            "not found",
            "Install Node.js 20+: https://nodejs.org/en/download",
        )
    version = run_command("node", "--version").stdout.strip()
    match = re.match(r"v(\d+)", version)
    major = int(match.group(1)) if match else 0
    return CheckResult(
        CheckGroup.AWS,
        "node",
        major >= MINIMUM_NODE_MAJOR,
        version or "unknown version",
        f"Install Node.js {MINIMUM_NODE_MAJOR}+: https://nodejs.org/en/download",
    )


def check_session_manager_plugin() -> CheckResult:
    if not shutil.which("session-manager-plugin"):
        return CheckResult(
            CheckGroup.AWS,
            "session-manager-plugin",
            False,
            "not found",
            SESSION_MANAGER_INSTALL,
        )
    result = run_command("session-manager-plugin", "--version")
    version = result.stdout.strip()
    return CheckResult(
        CheckGroup.AWS,
        "session-manager-plugin",
        result.returncode == 0 and bool(version),
        version or "version check failed",
        SESSION_MANAGER_INSTALL,
    )


def check_aws_credentials() -> CheckResult:
    result = run_command(
        "aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text"
    )
    passed = result.returncode == 0
    detail = f"account {result.stdout.strip()}" if passed else "no valid credentials"
    return CheckResult(
        CheckGroup.AWS,
        "aws credentials",
        passed,
        detail,
        "aws configure sso  # or export AWS_PROFILE",
    )


def check_region() -> CheckResult:
    region = os.environ.get("AWS_REGION", "")
    return CheckResult(
        CheckGroup.AWS,
        "AWS_REGION",
        bool(region),
        region or "not set",
        "cp .env.example .env  # then set AWS_REGION",
    )


def check_model_access(variable: str, region: str) -> CheckResult:
    model_id = os.environ.get(variable, "")
    if not model_id:
        return CheckResult(
            CheckGroup.AWS,
            variable,
            False,
            "not set",
            f"cp .env.example .env  # then set {variable}",
        )
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
        CheckGroup.AWS,
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
        CheckGroup.AWS,
        "cdk bootstrap",
        passed,
        f"CDKToolkit found in {region}" if passed else f"missing in {region} (CDK deploys there)",
        f"npx cdk bootstrap aws://<account>/{region}",
    )


def blocked_cdk_bootstrap() -> CheckResult:
    return CheckResult(
        CheckGroup.AWS,
        "cdk bootstrap",
        False,
        "not checked: AWS CLI, credentials, and AWS_REGION are required",
        "AWS_REGION=<region> npx cdk bootstrap aws://<account>/<region>",
    )


def check_aws_read_paths() -> CheckResult:
    probe = Path(__file__).with_name("smoke_aws_servers.py")
    result = run_command(sys.executable, str(probe), timeout=AWS_PROBE_TIMEOUT_SECONDS)
    failures = [line for line in result.stdout.splitlines() if line.startswith("FAIL")]
    detail = (
        "CMCD, MediaConnect, and MediaLive read paths passed"
        if result.returncode == 0
        else "; ".join(" ".join(line.split()) for line in failures)
        or f"read-only sample probe failed ({result.stderr.strip()[-200:] or 'no output'})"
    )
    return CheckResult(
        CheckGroup.AWS,
        "sample read paths",
        result.returncode == 0,
        detail,
        "Set the sample connection values in the root .env, then run just smoke aws",
    )


def collect_offline_results() -> list[CheckResult]:
    return [
        check_tool(
            "uv",
            "curl -LsSf https://astral.sh/uv/install.sh | sh",
            CheckGroup.OFFLINE,
        ),
        check_tool("just", "uv tool install rust-just", CheckGroup.OFFLINE),
        check_tool(
            "ffprobe",
            "Install FFmpeg (https://ffmpeg.org/download.html) for HLS Doctor media probes",
            CheckGroup.MEDIA,
        ),
        check_tool(
            "mediastreamvalidator",
            "Apple HLS Tools (macOS, optional) add the HLS Doctor conformance crosscheck",
            CheckGroup.MEDIA,
        ),
        check_python_version(),
    ]


def collect_aws_results() -> list[CheckResult]:
    aws_cli = check_tool(
        "aws",
        "Install AWS CLI v2: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html",
        CheckGroup.AWS,
    )
    region = check_region()
    results = [
        aws_cli,
        check_session_manager_plugin(),
        check_docker(),
        check_node(),
        check_tool(
            "npx",
            "Install Node.js 20+; each CDK app installs its own CDK with npm ci",
            CheckGroup.AWS,
        ),
        region,
    ]
    if not (aws_cli.passed and region.passed):
        return [*results, blocked_cdk_bootstrap()]

    credentials = check_aws_credentials()
    results.append(credentials)
    if not credentials.passed:
        return [*results, blocked_cdk_bootstrap()]

    results.extend(
        [
            check_model_access("AGENT_MODEL_ID", region.detail),
            check_model_access("THUMBNAIL_MODEL_ID", region.detail),
            check_cdk_bootstrap(region.detail),
        ]
    )
    return results


def collect_results() -> list[CheckResult]:
    return [*collect_offline_results(), *collect_aws_results()]


def print_results(results: list[CheckResult], *, strict_aws: bool) -> None:
    for group in CheckGroup:
        print(f"{group.value.upper()} prerequisites")
        for result in (item for item in results if item.group is group):
            failed_strictly = group is CheckGroup.OFFLINE or (
                strict_aws and group is CheckGroup.AWS
            )
            mark = "ok  " if result.passed else ("FAIL" if failed_strictly else "WARN")
            print(f"{mark} {result.name:<20} {result.detail}")
            if not result.passed:
                print(f"     fix: {result.fix}")
        print()


def parse_arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "group",
        nargs="?",
        choices=[CheckGroup.AWS],
        help="make AWS and deployment checks strict",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    arguments = parse_arguments(argv or [])
    strict_aws = arguments.group == CheckGroup.AWS
    results = collect_results()
    if strict_aws and all(result.passed for result in results):
        results.append(check_aws_read_paths())
    print_results(results, strict_aws=strict_aws)

    offline_failures = [
        result for result in results if result.group is CheckGroup.OFFLINE and not result.passed
    ]
    aws_failures = [
        result for result in results if result.group is CheckGroup.AWS and not result.passed
    ]
    blocking = [*offline_failures, *(aws_failures if strict_aws else [])]
    if blocking:
        print(f"{len(blocking)} required check(s) failed.")
        return 1
    if aws_failures:
        print(f"Offline development is ready. {len(aws_failures)} AWS warning(s).")
    else:
        print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
