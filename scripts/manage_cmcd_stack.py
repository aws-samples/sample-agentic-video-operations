"""`just deploy|destroy cmcd`: the cmcd CloudFormation stack (cloudfront-cmcd-kinesis.yaml).

CloudFront CMCD logs -> Kinesis -> Timestream for InfluxDB, behind a bastion.
Pinned to us-east-1: the template's WAF WebACL has Scope CLOUDFRONT, which AWS only allows there.

    uv run python scripts/manage_cmcd_stack.py deploy [--yes]
    uv run python scripts/manage_cmcd_stack.py destroy [--yes]
    uv run python scripts/manage_cmcd_stack.py show-next-steps
"""

import argparse
import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence

from confirm_aws_action import NO_CREDENTIALS_FIX, ConfirmationPrompt, ask_to_continue

STACK = "video-ops-cmcd"
REGION = "us-east-1"
TEMPLATE = "samples/cmcd/cloudfront-cmcd-kinesis.yaml"
DEPLOY_ACTION = (
    "deploy (billable: CloudFront, Kinesis, InfluxDB db.influx.medium, NAT gateway, EC2)"
)
DESTROY_ACTION = "destroy (deletes everything listed below)"

Runner = Callable[[Sequence[str], bool], subprocess.CompletedProcess[str]]


def run_aws(arguments: Sequence[str], capture: bool) -> subprocess.CompletedProcess[str]:
    """Run one AWS CLI command; capture output only for lookups."""
    return subprocess.run(["aws", *arguments], capture_output=capture, text=True, check=False)


def look_up(runner: Runner, arguments: Sequence[str]) -> str | None:
    result = runner(arguments, True)
    value = result.stdout.strip() if result.returncode == 0 else ""
    return value if value and value != "None" else None


def read_account_id(runner: Runner) -> str | None:
    return look_up(runner, ["sts", "get-caller-identity", "--query", "Account", "--output", "text"])


def read_stack_output(runner: Runner, key: str) -> str | None:
    query = f"Stacks[0].Outputs[?OutputKey=='{key}'].OutputValue"
    arguments = ["cloudformation", "describe-stacks", "--region", REGION, "--stack-name", STACK]
    return look_up(runner, [*arguments, "--query", query, "--output", "text"])


def deploy_stack(
    runner: Runner, *, assume_yes: bool, environ: Mapping[str, str], ask: Callable[[str], str]
) -> int:
    account = read_account_id(runner)
    if account is None:
        print(NO_CREDENTIALS_FIX)
        return 1
    prompt = ConfirmationPrompt(DEPLOY_ACTION, STACK, REGION, account)
    if not ask_to_continue(prompt, assume_yes=assume_yes, ask=ask):
        return 1
    origin = environ.get("CMCD_ORIGIN_DOMAIN") or "example.com"
    bucket = environ.get("CMCD_S3_BUCKET_NAME") or f"cmcd-content-{account}"
    result = runner(
        [
            "cloudformation", "deploy", "--region", REGION, "--stack-name", STACK,
            "--template-file", TEMPLATE, "--capabilities", "CAPABILITY_IAM", "CAPABILITY_NAMED_IAM",
            "--parameter-overrides", f"OriginDomainName={origin}", f"S3BucketName={bucket}",
        ],
        False,
    )  # fmt: skip
    if result.returncode != 0:
        return result.returncode
    return show_next_steps(runner)


def show_next_steps(runner: Runner) -> int:
    """Print how to connect the MCP server to the private InfluxDB through the bastion."""
    bastion = read_stack_output(runner, "BastionHostInstanceId")
    endpoint = read_stack_output(runner, "InfluxDBEndpoint")
    secret = read_stack_output(runner, "InfluxDBSecretArn")
    if not (bastion and endpoint and secret):
        print(f"Stack {STACK} not found in {REGION}, or it has no outputs yet.")
        return 1
    parameters = f'{{"host":["{endpoint}"],"portNumber":["8086"],"localPortNumber":["8086"]}}'
    print(f"""
Deployed. Video player: {read_stack_output(runner, "VideoPlayerURL")}

Connect the MCP server to InfluxDB (private subnet, reached through the bastion):
  1. Open a tunnel and keep it running:
     aws ssm start-session --region {REGION} --target {bastion} \\
       --document-name AWS-StartPortForwardingSessionToRemoteHost \\
       --parameters '{parameters}'
  2. Read the admin password:
     aws secretsmanager get-secret-value --region {REGION} --secret-id {secret} \\
       --query SecretString --output text
  3. Sign in at https://localhost:8086 as admin and create an API token
     (Load Data > API Tokens). The stack output InfluxDBToken is not an API token.
  4. Set in the root .env:
     INFLUXDB_URL=https://localhost:8086
     INFLUXDB_ORG=cmcd-org
     INFLUXDB_TOKEN=<the token from step 3>
     VERIFY_SSL=false   # only through the tunnel: the certificate names the InfluxDB host""")
    return 0


def read_lambda_log_groups(runner: Runner) -> list[str] | None:
    """Log groups the stack's Lambdas created (CloudFormation does not delete them).

    Returns None when the lookup itself fails, so destroy never mistakes "unknown" for "none".
    """
    result = runner(
        [
            "logs", "describe-log-groups", "--region", REGION,
            "--log-group-name-prefix", f"/aws/lambda/{STACK}-",
            "--query", "logGroups[].logGroupName", "--output", "text",
        ],
        True,
    )  # fmt: skip
    if result.returncode != 0:
        return None
    names = result.stdout.strip()
    return [] if names in ("", "None") else names.split()


def destroy_stack(runner: Runner, *, assume_yes: bool, ask: Callable[[str], str]) -> int:
    """Delete everything deploy created, after one confirmation that lists all of it.

    The template keeps DeletionPolicy: Retain on the InfluxDB instance, so a stack deleted
    outside this command never loses data silently; this command deletes it explicitly.
    """
    account = read_account_id(runner)
    if account is None:
        print(NO_CREDENTIALS_FIX)
        return 1
    bucket = read_stack_output(runner, "S3BucketName")
    influxdb = read_stack_output(runner, "InfluxDBInstanceId")
    if not (bucket and influxdb):
        print(f"Stack {STACK} not found in {REGION}; nothing to destroy.")
        return 1
    log_groups = read_lambda_log_groups(runner)
    if log_groups is None:
        print("Could not list the stack's Lambda log groups (logs:DescribeLogGroups failed).")
        print("Nothing was deleted. Fix the credentials or permissions, then re-run.")
        return 1
    details = {
        "content bucket (emptied)": bucket,
        "stack (deleted)": STACK,
        "InfluxDB instance (deleted)": influxdb,
        "log groups (deleted)": ", ".join(log_groups) or "none",
    }
    prompt = ConfirmationPrompt(DESTROY_ACTION, STACK, REGION, account, details)
    if not ask_to_continue(prompt, assume_yes=assume_yes, ask=ask):
        return 1
    steps = [
        ["s3", "rm", f"s3://{bucket}", "--recursive", "--region", REGION],
        ["cloudformation", "delete-stack", "--region", REGION, "--stack-name", STACK],
        ["cloudformation", "wait", "stack-delete-complete", "--region", REGION,
         "--stack-name", STACK],
        ["timestream-influxdb", "delete-db-instance", "--region", REGION, "--identifier", influxdb],
        *(
            ["logs", "delete-log-group", "--region", REGION, "--log-group-name", name]
            for name in log_groups
        ),
    ]  # fmt: skip
    for arguments in steps:
        result = runner(arguments, False)
        if result.returncode != 0:
            print(f"Stopped: `aws {' '.join(arguments)}` failed. Re-run `just destroy cmcd`.")
            return result.returncode
    print(f"""Deleted stack {STACK}, its content, and {len(log_groups)} log group(s).
InfluxDB instance {influxdb} is being deleted (takes several minutes). Check with:
  aws timestream-influxdb get-db-instance --region {REGION} --identifier {influxdb}
KMS keys created by the stack are scheduled for deletion by AWS (7-30 days); no action needed.""")
    return 0


def main(argv: Sequence[str], runner: Runner = run_aws, ask: Callable[[str], str] = input) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["deploy", "destroy", "show-next-steps"])
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    arguments = parser.parse_args(argv)
    if arguments.command == "deploy":
        return deploy_stack(runner, assume_yes=arguments.yes, environ=os.environ, ask=ask)
    if arguments.command == "destroy":
        return destroy_stack(runner, assume_yes=arguments.yes, ask=ask)
    return show_next_steps(runner)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
