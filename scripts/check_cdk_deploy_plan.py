"""Before a CDK deploy builds anything: the bootstrap state and the security changes (T59).

The repository's confirmation is the one place a person approves a deploy. It comes after
the security diff is printed and before the image is built or pushed, so CDK then deploys
with `--require-approval never` and never stops halfway to ask again.
"""

import json
import re
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from read_aws_cli_error import describe_failure, is_missing_resource

Runner = Callable[[Sequence[str], Path | None, bool], subprocess.CompletedProcess[str]]
USABLE_BOOTSTRAP = {"CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE"}
DEFAULT_QUALIFIER = "hnb659fds"  # CDK's own default; neither app sets another
QUALIFIER_CONTEXT = "@aws-cdk/core:bootstrapQualifier"
MINIMUM_BOOTSTRAP_VERSION = 6  # the synthesized CheckBootstrapVersion rule rejects 1-5
NO_SECURITY_CHANGES = "There were no security-related changes"
# The section headers CDK prints when there are security changes (cloudformation-diff).
SECURITY_SECTIONS = ("IAM Statement Changes", "IAM Policy Changes", "Security Group Changes")
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def check_cdk_bootstrap(
    runner: Runner, region: str, account: str, cdk_directory: Path
) -> str | None:
    """The confirmation's bootstrap line, or None after printing why the deploy can't go on.

    A healthy CDKToolkit is not enough: the app synthesizes for one qualifier's resources
    (`cdk-<qualifier>-…` roles and buckets), so the stack's Qualifier parameter must match and
    `/cdk-bootstrap/<qualifier>/version` must be one the synthesized template accepts."""
    qualifier = expected_qualifier(cdk_directory)
    target = f"aws://{account}/{region}"
    result = runner(
        [
            "aws", "cloudformation", "describe-stacks", "--stack-name", "CDKToolkit",
            "--region", region, "--output", "json", "--query",
            "Stacks[0].{status: StackStatus, "
            "qualifier: Parameters[?ParameterKey=='Qualifier'] | [0].ParameterValue}",
        ],
        cdk_directory,
        True,
    )  # fmt: skip
    if result.returncode != 0:
        if is_missing_resource(result):
            print(f"CDK bootstrap: missing in {target}. Run, once:")
            print(f"  (cd {cdk_directory} && npx cdk bootstrap {target})")
        else:
            print(f"CDK bootstrap: could not be read: {describe_failure(result)}")
        return stopped()
    found = read_json_object(result.stdout)
    status, found_qualifier = found.get("status"), found.get("qualifier")
    if status not in USABLE_BOOTSTRAP:
        print(f"CDK bootstrap: CDKToolkit is {status or 'unreadable'} in {target}.")
        print("Fix or re-create it with `npx cdk bootstrap`, then re-run the deploy.")
        return stopped()
    if found_qualifier != qualifier:
        described = f"qualifier {found_qualifier}" if found_qualifier else "no Qualifier (legacy)"
        print(
            f"CDK bootstrap: CDKToolkit in {target} has {described}, but this app deploys "
            f"through the {qualifier} bootstrap resources."
        )
        print(f"  Bootstrap for it: (cd {cdk_directory} && npx cdk bootstrap {target})")
        return stopped()
    version = read_bootstrap_version(runner, region, qualifier, cdk_directory)
    if version is None:
        return stopped()
    return f"found (CDKToolkit, qualifier {qualifier}, version {version})"


def expected_qualifier(cdk_directory: Path) -> str:
    """The qualifier the app synthesizes for: cdk.json's context, else CDK's default."""
    try:
        context = json.loads((cdk_directory / "cdk.json").read_text()).get("context", {})
    except (OSError, ValueError):
        return DEFAULT_QUALIFIER
    return str(context.get(QUALIFIER_CONTEXT) or DEFAULT_QUALIFIER)


def read_bootstrap_version(
    runner: Runner, region: str, qualifier: str, cdk_directory: Path
) -> int | None:
    name = f"/cdk-bootstrap/{qualifier}/version"
    result = runner(
        [
            "aws", "ssm", "get-parameter", "--name", name, "--region", region,
            "--query", "Parameter.Value", "--output", "text",
        ],
        cdk_directory,
        True,
    )  # fmt: skip
    if result.returncode != 0:
        reason = "is missing" if is_missing_resource(result) else describe_failure(result)
        print(f"CDK bootstrap: the version parameter {name} {reason}.")
        print("Re-run `npx cdk bootstrap` for this account and Region, then deploy again.")
        return None
    value = result.stdout.strip()
    if not value.isdigit() or int(value) < MINIMUM_BOOTSTRAP_VERSION:
        print(
            f"CDK bootstrap: {name} is {value or 'empty'}; this app needs version "
            f"{MINIMUM_BOOTSTRAP_VERSION} or later. Re-run `npx cdk bootstrap`."
        )
        return None
    return int(value)


def read_json_object(text: str) -> dict[str, str | None]:
    try:
        value = json.loads(text)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def stopped() -> None:
    print("Nothing was built or deployed.")
    return None


def approval_line(assume_yes: bool) -> str:
    """Say plainly who approves the IAM changes: CDK itself never asks."""
    if assume_yes:
        return "given by --yes (no prompt): CDK deploys with --require-approval never"
    return "this confirmation: CDK then deploys with --require-approval never"


def show_security_diff(
    runner: Runner, cdk: Path, stack: str, context: Sequence[str], cdk_directory: Path
) -> str | None:
    """Print the IAM and security-group changes this deploy would make, from templates only:
    `--method template` creates no change set and needs no built image.

    Returns the confirmation's "security changes" line, or None to stop. The output is read,
    not just streamed, and only CDK's own result for this stack backs an approval: a
    `Stack <stack>` line followed by CDK's "no changes" sentence or a security-change section.
    Anything else (nothing, a warning or notice alone, another stack) stops the deploy."""
    print("Security changes this deploy makes (IAM statements, policies, security groups):")
    result = runner(
        [str(cdk), "diff", stack, *context, "--security-only", "--method", "template"],
        cdk_directory,
        True,
    )
    shown = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    if shown:
        print(shown)
    if result.returncode != 0:
        print("Could not compute the security diff, so nothing was built or deployed.")
        return None
    outcome = read_security_outcome(shown, stack)
    if outcome is None:
        print(
            f"CDK printed no security diff for {stack}, so nothing was built or deployed."
            if shown
            else "The security diff printed nothing, so nothing was built or deployed."
        )
    return outcome


def read_security_outcome(shown: str, stack: str) -> str | None:
    """CDK's result for `stack`: only its own section counts, from its `Stack <stack>` line
    to the next `Stack ` line or the end. Another stack's result never authorizes this one."""
    lines = [line.strip() for line in ANSI_ESCAPE.sub("", shown).splitlines()]
    try:
        start = lines.index(f"Stack {stack}") + 1
    except ValueError:
        return None
    after = []
    for line in lines[start:]:
        if line.startswith("Stack "):
            break
        after.append(line)
    if any(line in SECURITY_SECTIONS for line in after):
        return "listed above"
    if any(line.startswith(NO_SECURITY_CHANGES) for line in after):
        return "none (cdk diff: no security-related changes)"
    return None
