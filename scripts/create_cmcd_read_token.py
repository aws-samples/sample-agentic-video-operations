"""Create the CMCD bucket read token and store its local connection settings."""

import json
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from create_influxdb_read_token import (
    InfluxAdminCredentials,
    InfluxApiError,
    create_influxdb_read_token,
)
from write_root_env_values import write_root_env_values

Runner = Callable[[Sequence[str], bool], subprocess.CompletedProcess[str]]
TokenCreator = Callable[[str, InfluxAdminCredentials], str]


@dataclass(frozen=True)
class CreateReadTokenRequest:
    stack: str
    region: str
    tunnel_url: str
    assume_yes: bool
    env_path: Path
    env_example_path: Path


@dataclass(frozen=True)
class CreateReadTokenDependencies:
    runner: Runner
    ask: Callable[[str], str]
    token_creator: TokenCreator = create_influxdb_read_token


def _look_up(runner: Runner, arguments: Sequence[str]) -> str | None:
    result = runner(arguments, True)
    value = result.stdout.strip() if result.returncode == 0 else ""
    return value if value and value != "None" else None


def _read_account_id(runner: Runner) -> str | None:
    return _look_up(
        runner,
        ["sts", "get-caller-identity", "--query", "Account", "--output", "text"],
    )


def _read_stack_output(
    runner: Runner,
    stack: str,
    region: str,
    output_key: str,
) -> str | None:
    query = f"Stacks[0].Outputs[?OutputKey=='{output_key}'].OutputValue"
    return _look_up(
        runner,
        [
            "cloudformation",
            "describe-stacks",
            "--region",
            region,
            "--stack-name",
            stack,
            "--query",
            query,
            "--output",
            "text",
        ],
    )


def _read_influxdb_credentials(
    runner: Runner,
    secret_arn: str,
    region: str,
) -> InfluxAdminCredentials:
    result = runner(
        [
            "secretsmanager",
            "get-secret-value",
            "--region",
            region,
            "--secret-id",
            secret_arn,
            "--query",
            "SecretString",
            "--output",
            "text",
        ],
        True,
    )
    if result.returncode != 0:
        raise ValueError("Could not read the InfluxDB secret.")
    try:
        secret = json.loads(result.stdout)
        return InfluxAdminCredentials(
            username=secret["username"],
            password=secret["password"],
            organization=secret["organization"],
            bucket=secret["bucket"],
            read_token=secret.get("readToken"),
        )
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise ValueError("The InfluxDB secret is missing required fields.") from error


def create_cmcd_read_token(
    request: CreateReadTokenRequest,
    dependencies: CreateReadTokenDependencies,
) -> int:
    """Confirm, create one least-privilege token, and silently update root .env."""
    account = _read_account_id(dependencies.runner)
    secret_arn = _read_stack_output(
        dependencies.runner,
        request.stack,
        request.region,
        "InfluxDBSecretArn",
    )
    bucket = _read_stack_output(
        dependencies.runner,
        request.stack,
        request.region,
        "InfluxDBBucketName",
    )
    if account is None or secret_arn is None or bucket is None:
        print(
            f"Stack {request.stack} not found in {request.region}, "
            "its CMCD bucket output is unavailable, or AWS credentials are unavailable."
        )
        return 1
    if (
        not request.assume_yes
        and dependencies.ask(
            "Create or reuse the bucket-scoped InfluxDB read token and update root .env? [y/N] "
        )
        .strip()
        .lower()
        != "y"
    ):
        return 1
    try:
        credentials = _read_influxdb_credentials(
            dependencies.runner,
            secret_arn,
            request.region,
        )
        credentials = InfluxAdminCredentials(
            username=credentials.username,
            password=credentials.password,
            organization=credentials.organization,
            bucket=bucket,
            read_token=credentials.read_token,
        )
        token = dependencies.token_creator(request.tunnel_url, credentials)
        write_root_env_values(
            request.env_path,
            request.env_example_path,
            {
                "INFLUXDB_URL": request.tunnel_url,
                "INFLUXDB_ORG": credentials.organization,
                "INFLUXDB_BUCKET": credentials.bucket,
                "INFLUXDB_TOKEN": token,
                "VERIFY_SSL": "false",
            },
        )
    except (InfluxApiError, ValueError, OSError) as error:
        print(error)
        return 1
    print("written")
    return 0
