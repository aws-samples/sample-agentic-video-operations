"""`just deploy|destroy cmcd`: the cmcd CloudFormation stack (cloudfront-cmcd-kinesis.yaml).

CloudFront CMCD logs -> Kinesis -> Timestream for InfluxDB, behind a bastion.
Pinned to us-east-1: the template's WAF WebACL has Scope CLOUDFRONT, which AWS only allows there.

    uv run python scripts/manage_cmcd_stack.py deploy [--yes]
    uv run python scripts/manage_cmcd_stack.py destroy [--yes]
    uv run python scripts/manage_cmcd_stack.py show-next-steps
    uv run python scripts/manage_cmcd_stack.py create-read-token [--yes]
"""

import argparse
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from confirm_aws_action import NO_CREDENTIALS_FIX, ConfirmationPrompt, ask_to_continue
from create_cmcd_read_token import (
    CreateReadTokenDependencies,
    CreateReadTokenRequest,
    TokenCreator,
    create_cmcd_read_token,
)
from create_influxdb_read_token import create_influxdb_read_token
from destroy_cmcd_stack import (
    REGION,
    STACK,
    artifact_bucket_name,
    destroy_cmcd_stack,
    failure_detail,
    is_missing_resource,
)

TEMPLATE = "samples/cmcd/cloudfront-cmcd-kinesis.yaml"
DEPLOY_ACTION = (
    "deploy (billable: CloudFront, Kinesis, InfluxDB db.influx.medium, NAT gateway, EC2)"
)
TUNNEL_URL = "https://localhost:8086"

Runner = Callable[[Sequence[str], bool], subprocess.CompletedProcess[str]]
BUCKET_ALREADY_EXISTS = re.compile(r"An error occurred \(BucketAlreadyExists\)")


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


def explain_foreign_bucket(bucket: str) -> None:
    print(
        f"Deployment artifacts bucket {bucket} is not owned by this AWS account. "
        "Set CMCD_ARTIFACTS_BUCKET to a bucket name you own."
    )


def verify_artifact_bucket_owner(runner: Runner, bucket: str, account: str) -> int:
    result = runner(
        [
            "s3api",
            "head-bucket",
            "--bucket",
            bucket,
            "--region",
            REGION,
            "--expected-bucket-owner",
            account,
        ],
        True,
    )
    if result.returncode != 0:
        explain_foreign_bucket(bucket)
        print(f"AWS detail: {failure_detail(result)}")
    return result.returncode


def prepare_artifact_bucket(runner: Runner, bucket: str, account: str) -> int:
    """Create and secure the bucket used by CloudFormation for oversized templates."""
    lookup = runner(
        [
            "s3api", "head-bucket", "--bucket", bucket, "--region", REGION,
            "--expected-bucket-owner", account,
        ],
        True,
    )  # fmt: skip
    if lookup.returncode != 0:
        if not is_missing_resource(lookup):
            explain_foreign_bucket(bucket)
            print(f"AWS detail: {failure_detail(lookup)}")
            return lookup.returncode
        created = runner(
            ["s3api", "create-bucket", "--bucket", bucket, "--region", REGION],
            True,
        )
        if created.returncode != 0:
            if BUCKET_ALREADY_EXISTS.search(f"{created.stdout}\n{created.stderr}"):
                explain_foreign_bucket(bucket)
                return created.returncode
            print(
                f"Could not create deployment artifact bucket {bucket}: {failure_detail(created)}"
            )
            return created.returncode
    public_access = runner(
        [
            "s3api",
            "put-public-access-block",
            "--bucket",
            bucket,
            "--region",
            REGION,
            "--expected-bucket-owner",
            account,
            "--public-access-block-configuration",
            (
                "BlockPublicAcls=true,IgnorePublicAcls=true,"
                "BlockPublicPolicy=true,RestrictPublicBuckets=true"
            ),
        ],
        True,
    )
    if public_access.returncode != 0:
        print(
            f"Could not block public access on deployment artifact bucket {bucket}: "
            f"{failure_detail(public_access)}"
        )
        return public_access.returncode
    encryption = runner(
        [
            "s3api",
            "put-bucket-encryption",
            "--bucket",
            bucket,
            "--region",
            REGION,
            "--expected-bucket-owner",
            account,
            "--server-side-encryption-configuration",
            '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}',
        ],
        True,
    )
    if encryption.returncode != 0:
        print(
            f"Could not enable encryption on deployment artifact bucket {bucket}: "
            f"{failure_detail(encryption)}"
        )
        return encryption.returncode
    return 0


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
    artifacts = environ.get("CMCD_ARTIFACTS_BUCKET") or artifact_bucket_name(account)
    status = prepare_artifact_bucket(runner, artifacts, account)
    if status != 0:
        return status
    status = verify_artifact_bucket_owner(runner, artifacts, account)
    if status != 0:
        return status
    result = runner(
        [
            "cloudformation", "deploy", "--region", REGION, "--stack-name", STACK,
            "--template-file", TEMPLATE, "--capabilities", "CAPABILITY_IAM", "CAPABILITY_NAMED_IAM",
            "--s3-bucket", artifacts, "--s3-prefix", STACK,
            "--parameter-overrides", f"OriginDomainName={origin}", f"S3BucketName={bucket}",
            f"DeploymentArtifactsBucketName={artifacts}",
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
       --query SecretString --output text | \\
       python3 -c 'import json,sys; print(json.load(sys.stdin)["password"])'
  3. Create a bucket-scoped read token and write the connection to root .env:
     uv run python scripts/manage_cmcd_stack.py create-read-token

The token command does not print the password or token. VERIFY_SSL=false is used only through
the tunnel because the certificate names the private InfluxDB host, not localhost.""")
    return 0


def main(
    argv: Sequence[str],
    runner: Runner = run_aws,
    ask: Callable[[str], str] = input,
    token_creator: TokenCreator = create_influxdb_read_token,
    env_path: Path = Path(".env"),
    env_example_path: Path = Path(".env.example"),
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=["deploy", "destroy", "show-next-steps", "create-read-token"],
    )
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    arguments = parser.parse_args(argv)
    if arguments.command == "deploy":
        return deploy_stack(runner, assume_yes=arguments.yes, environ=os.environ, ask=ask)
    if arguments.command == "destroy":
        return destroy_cmcd_stack(runner, assume_yes=arguments.yes, ask=ask)
    if arguments.command == "create-read-token":
        return create_cmcd_read_token(
            CreateReadTokenRequest(
                stack=STACK,
                region=REGION,
                tunnel_url=TUNNEL_URL,
                assume_yes=arguments.yes,
                env_path=env_path,
                env_example_path=env_example_path,
            ),
            CreateReadTokenDependencies(
                runner=runner,
                ask=ask,
                token_creator=token_creator,
            ),
        )
    return show_next_steps(runner)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
