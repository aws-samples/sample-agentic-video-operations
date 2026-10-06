"""Delete the CMCD stack without leaving its retained InfluxDB instance."""

import re
import subprocess
import time
from collections.abc import Callable, Sequence

from confirm_aws_action import NO_CREDENTIALS_FIX, ConfirmationPrompt, ask_to_continue

STACK = "video-ops-cmcd"
REGION = "us-east-1"
DESTROY_ACTION = "destroy (deletes everything listed below)"
INFLUXDB_DELETE_TIMEOUT_SECONDS = 1800
INFLUXDB_POLL_SECONDS = 15
UNSAFE_LOOKUP_STATUS = 70

Runner = Callable[[Sequence[str], bool], subprocess.CompletedProcess[str]]
MISSING_ERROR_CODE = re.compile(
    r"An error occurred \((ResourceNotFoundException|NoSuchBucket|NotFound|404)\)"
)
MISSING_STACK = re.compile(r"Stack with id .+ does not exist")


def look_up(runner: Runner, arguments: Sequence[str]) -> str | None:
    result = runner(arguments, True)
    value = result.stdout.strip() if result.returncode == 0 else ""
    return value if value and value != "None" else None


def read_account_id(runner: Runner) -> str | None:
    return look_up(runner, ["sts", "get-caller-identity", "--query", "Account", "--output", "text"])


def is_missing_resource(result: subprocess.CompletedProcess[str]) -> bool:
    message = f"{result.stdout}\n{result.stderr}"
    return bool(MISSING_ERROR_CODE.search(message) or MISSING_STACK.search(message))


def failure_detail(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout).strip() or f"AWS CLI exited {result.returncode}"


def read_stack_presence(runner: Runner) -> bool | None:
    result = runner(
        [
            "cloudformation",
            "describe-stacks",
            "--region",
            REGION,
            "--stack-name",
            STACK,
            "--query",
            "Stacks[0].StackStatus",
            "--output",
            "text",
        ],
        True,
    )
    if result.returncode == 0:
        return True
    return False if is_missing_resource(result) else None


def read_stack_output(runner: Runner, key: str) -> str | None:
    query = f"Stacks[0].Outputs[?OutputKey=='{key}'].OutputValue"
    arguments = ["cloudformation", "describe-stacks", "--region", REGION, "--stack-name", STACK]
    return look_up(runner, [*arguments, "--query", query, "--output", "text"])


def read_stack_resource_id(runner: Runner, logical_id: str) -> str | None:
    return look_up(
        runner,
        [
            "cloudformation",
            "describe-stack-resource",
            "--region",
            REGION,
            "--stack-name",
            STACK,
            "--logical-resource-id",
            logical_id,
            "--query",
            "StackResourceDetail.PhysicalResourceId",
            "--output",
            "text",
        ],
    )


def read_lambda_log_groups(runner: Runner) -> list[str] | None:
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


def read_influxdb_status(
    runner: Runner, identifier: str
) -> tuple[str | None, subprocess.CompletedProcess[str]]:
    result = runner(
        [
            "timestream-influxdb",
            "get-db-instance",
            "--region",
            REGION,
            "--identifier",
            identifier,
            "--query",
            "status",
            "--output",
            "text",
        ],
        True,
    )
    if result.returncode != 0:
        return (None, result)
    return (result.stdout.strip().upper(), result)


def wait_for_influxdb_deletion(
    runner: Runner,
    identifier: str,
    *,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    timeout_seconds: int = INFLUXDB_DELETE_TIMEOUT_SECONDS,
) -> int:
    deadline = monotonic() + timeout_seconds
    while True:
        _, result = read_influxdb_status(runner, identifier)
        if result.returncode != 0:
            if is_missing_resource(result):
                return 0
            print(
                f"Could not read InfluxDB instance {identifier} while waiting for deletion: "
                f"{failure_detail(result)}"
            )
            return UNSAFE_LOOKUP_STATUS
        remaining = deadline - monotonic()
        if remaining <= 0:
            print(
                f"Timed out after {timeout_seconds}s waiting for InfluxDB instance "
                f"{identifier} to be deleted."
            )
            return 1
        sleep(min(INFLUXDB_POLL_SECONDS, remaining))


def delete_influxdb_if_present(
    runner: Runner,
    identifier: str,
    *,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> int:
    status, lookup = read_influxdb_status(runner, identifier)
    if lookup.returncode != 0:
        if is_missing_resource(lookup):
            print(f"InfluxDB instance {identifier} is already absent.")
            return 0
        print(f"Could not read InfluxDB instance {identifier}: {failure_detail(lookup)}")
        return UNSAFE_LOOKUP_STATUS
    if status != "DELETING":
        result = runner(
            [
                "timestream-influxdb",
                "delete-db-instance",
                "--region",
                REGION,
                "--identifier",
                identifier,
            ],
            True,
        )
        if result.returncode != 0 and not is_missing_resource(result):
            print(f"Could not delete InfluxDB instance {identifier}: {failure_detail(result)}")
            return result.returncode
    return wait_for_influxdb_deletion(
        runner,
        identifier,
        sleep=sleep,
        monotonic=monotonic,
    )


def empty_bucket_if_present(runner: Runner, bucket: str) -> int:
    lookup = runner(
        ["s3api", "head-bucket", "--bucket", bucket, "--region", REGION],
        True,
    )
    if lookup.returncode != 0:
        if is_missing_resource(lookup):
            print(f"S3 bucket {bucket} is already absent.")
            return 0
        print(f"Could not read S3 bucket {bucket}: {failure_detail(lookup)}")
        return lookup.returncode
    result = runner(
        [
            "s3",
            "rm",
            f"s3://{bucket}",
            "--recursive",
            "--only-show-errors",
            "--region",
            REGION,
        ],
        True,
    )
    if result.returncode != 0 and not is_missing_resource(result):
        print(f"Could not empty S3 bucket {bucket}: {failure_detail(result)}")
        return result.returncode
    return 0


def delete_stack_if_present(runner: Runner) -> int:
    result = runner(
        ["cloudformation", "delete-stack", "--region", REGION, "--stack-name", STACK],
        True,
    )
    if result.returncode != 0:
        if is_missing_resource(result):
            print(f"CloudFormation stack {STACK} is already absent.")
            return 0
        print(f"Could not delete CloudFormation stack {STACK}: {failure_detail(result)}")
        return result.returncode
    result = runner(
        [
            "cloudformation",
            "wait",
            "stack-delete-complete",
            "--region",
            REGION,
            "--stack-name",
            STACK,
        ],
        False,
    )
    if result.returncode != 0 and not is_missing_resource(result):
        print(f"CloudFormation stack {STACK} did not finish deleting.")
        return result.returncode
    return 0


def delete_log_groups_if_present(runner: Runner, log_groups: Sequence[str]) -> list[str]:
    failed: list[str] = []
    for name in log_groups:
        result = runner(
            ["logs", "delete-log-group", "--region", REGION, "--log-group-name", name],
            True,
        )
        if result.returncode != 0 and not is_missing_resource(result):
            print(f"Could not delete Lambda log group {name}: {failure_detail(result)}")
            failed.append(name)
    return failed


def print_remaining_resources(resources: Sequence[tuple[str, str]]) -> None:
    print("Teardown incomplete. Remaining resources:")
    for label, identifier in resources:
        print(f"- {label}: {identifier}")
    print("Fix the reported AWS error(s), then re-run `just destroy cmcd`.")


def destroy_cmcd_stack(
    runner: Runner,
    *,
    assume_yes: bool,
    ask: Callable[[str], str],
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> int:
    """Delete InfluxDB before the stack so its ENIs cannot block VPC deletion."""
    account = read_account_id(runner)
    if account is None:
        print(NO_CREDENTIALS_FIX)
        return 1
    stack_exists = read_stack_presence(runner)
    if stack_exists is None:
        print(f"Could not read CloudFormation stack {STACK}; nothing was deleted.")
        return 1
    bucket = read_stack_output(runner, "S3BucketName") if stack_exists else None
    influxdb = read_stack_output(runner, "InfluxDBInstanceId") if stack_exists else None
    if stack_exists:
        influxdb = influxdb or read_stack_resource_id(runner, "InfluxDBInstance")
        bucket = bucket or read_stack_resource_id(runner, "ContentBucket")
    log_groups = read_lambda_log_groups(runner)
    if log_groups is None:
        print("Could not list the stack's Lambda log groups (logs:DescribeLogGroups failed).")
        print("Nothing was deleted. Fix the credentials or permissions, then re-run.")
        return 1
    if stack_exists and not (bucket and influxdb):
        print(f"Stack {STACK} is missing required teardown outputs; nothing was deleted.")
        return 1
    if not stack_exists and not log_groups:
        print(f"Stack {STACK} and its stack-prefixed Lambda log groups are already absent.")
        return 0
    details = {
        "InfluxDB instance (deleted first)": influxdb or "already absent",
        "content bucket (emptied)": bucket or "already absent",
        "stack (deleted)": STACK if stack_exists else "already absent",
        "log groups (deleted)": ", ".join(log_groups) or "none",
    }
    prompt = ConfirmationPrompt(DESTROY_ACTION, STACK, REGION, account, details)
    if not ask_to_continue(prompt, assume_yes=assume_yes, ask=ask):
        return 1
    influxdb_remaining = bool(influxdb)
    bucket_remaining = bool(bucket)
    stack_remaining = stack_exists
    if influxdb:
        status = delete_influxdb_if_present(
            runner,
            influxdb,
            sleep=sleep,
            monotonic=monotonic,
        )
        if status == 0:
            influxdb_remaining = False
    else:
        status = 0
    if status == 0 and bucket:
        status = empty_bucket_if_present(runner, bucket)
    if status == 0 and stack_exists:
        status = delete_stack_if_present(runner)
        if status == 0:
            bucket_remaining = False
            stack_remaining = False
    failed_log_groups = (
        list(log_groups)
        if status == UNSAFE_LOOKUP_STATUS
        else delete_log_groups_if_present(runner, log_groups)
    )
    if status != 0 or failed_log_groups:
        remaining: list[tuple[str, str]] = []
        if influxdb_remaining and influxdb:
            remaining.append(("InfluxDB instance or deletion status unknown", influxdb))
        if bucket_remaining and bucket:
            remaining.append(("content bucket", bucket))
        if stack_remaining:
            remaining.append(("CloudFormation stack", STACK))
        remaining.extend(("Lambda log group", name) for name in failed_log_groups)
        print_remaining_resources(remaining)
        return 1
    print(
        f"Teardown complete for {STACK}: retained InfluxDB instance, content, stack, "
        f"and {len(log_groups)} log group(s) are absent.\n"
        "KMS keys created by the stack are scheduled for deletion by AWS (7-30 days); "
        "no action needed."
    )
    return 0
