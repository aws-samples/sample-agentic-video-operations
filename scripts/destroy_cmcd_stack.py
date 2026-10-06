"""Delete the CMCD stack without leaving its retained InfluxDB instance."""

import json
import os
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
PROVISIONING_CUSTOM_RESOURCE = "UpdateSecretCustomResource"

Runner = Callable[[Sequence[str], bool], subprocess.CompletedProcess[str]]
MISSING_ERROR_CODE = re.compile(
    r"An error occurred \((ResourceNotFoundException|NoSuchBucket|NotFound|404)\)"
)
MISSING_STACK = re.compile(r"Stack with id .+ does not exist")
CUSTOM_RESOURCE_NO_RESPONSE = re.compile(
    r"(did not receive a response from your custom resource|"
    r"timed out waiting for (a )?response from (the )?custom resource)",
    re.IGNORECASE,
)


def artifact_bucket_name(account: str) -> str:
    return f"{STACK}-artifacts-{account}-{REGION}"


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


def read_stack_status(
    runner: Runner,
) -> tuple[str | None, subprocess.CompletedProcess[str]]:
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
    status = result.stdout.strip() if result.returncode == 0 else None
    return status, result


def read_stack_presence(runner: Runner) -> bool | None:
    status, result = read_stack_status(runner)
    if result.returncode == 0:
        return bool(status)
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


def read_stack_resource_status_reason(runner: Runner, logical_id: str) -> tuple[str, str] | None:
    result = runner(
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
            "StackResourceDetail.[ResourceStatus,ResourceStatusReason]",
            "--output",
            "json",
        ],
        True,
    )
    if result.returncode != 0:
        print(f"Could not inspect {logical_id}: {failure_detail(result)}")
        return None
    try:
        values = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"Could not inspect {logical_id}: AWS returned malformed JSON.")
        return None
    if not isinstance(values, list) or len(values) != 2:
        print(f"Could not inspect {logical_id}: AWS returned an unexpected resource shape.")
        return None
    status, reason = values
    return str(status or ""), str(reason or "")


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


def empty_bucket_if_present(
    runner: Runner, bucket: str, *, expected_owner: str | None = None
) -> int:
    owner = ["--expected-bucket-owner", expected_owner] if expected_owner else []
    lookup = runner(
        ["s3api", "head-bucket", "--bucket", bucket, "--region", REGION, *owner],
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


def read_bucket_presence(runner: Runner, bucket: str, account: str) -> bool | None:
    result = runner(
        [
            "s3api", "head-bucket", "--bucket", bucket, "--region", REGION,
            "--expected-bucket-owner", account,
        ],
        True,
    )  # fmt: skip
    if result.returncode == 0:
        return True
    return False if is_missing_resource(result) else None


def delete_artifact_bucket_if_present(runner: Runner, bucket: str, account: str) -> int:
    status = empty_bucket_if_present(runner, bucket, expected_owner=account)
    if status != 0:
        return status
    result = runner(
        [
            "s3api",
            "delete-bucket",
            "--bucket",
            bucket,
            "--region",
            REGION,
            "--expected-bucket-owner",
            account,
        ],
        True,
    )
    if result.returncode != 0 and not is_missing_resource(result):
        print(f"Could not delete deployment artifact bucket {bucket}: {failure_detail(result)}")
        return result.returncode
    return 0


def wait_for_stack_deletion(runner: Runner) -> subprocess.CompletedProcess[str]:
    return runner(
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


def token_custom_resource_missed_response(runner: Runner) -> bool:
    stack_status, stack_lookup = read_stack_status(runner)
    if stack_lookup.returncode != 0 or stack_status != "DELETE_FAILED":
        return False
    resource = read_stack_resource_status_reason(runner, PROVISIONING_CUSTOM_RESOURCE)
    if resource is None:
        return False
    resource_status, reason = resource
    return resource_status == "DELETE_FAILED" and bool(CUSTOM_RESOURCE_NO_RESPONSE.search(reason))


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
    result = wait_for_stack_deletion(runner)
    if result.returncode == 0 or is_missing_resource(result):
        return 0
    if token_custom_resource_missed_response(runner):
        print(
            "The token custom resource could not return its delete response. "
            "Retrying the failed stack deletion while retaining only its inert "
            "custom-resource record."
        )
        retry = runner(
            [
                "cloudformation",
                "delete-stack",
                "--region",
                REGION,
                "--stack-name",
                STACK,
                "--retain-resources",
                PROVISIONING_CUSTOM_RESOURCE,
            ],
            True,
        )
        if retry.returncode != 0:
            print(f"Could not retry CloudFormation stack deletion: {failure_detail(retry)}")
            return retry.returncode
        result = wait_for_stack_deletion(runner)
        if result.returncode == 0 or is_missing_resource(result):
            return 0
    print(f"CloudFormation stack {STACK} did not finish deleting.")
    return result.returncode


def find_remaining_resources(
    runner: Runner,
    account: str,
    *,
    influxdb: str | None,
    content_bucket: str | None,
    artifact_bucket: str,
) -> list[tuple[str, str]]:
    """Look up every possible leftover after cleanup; never infer absence from a command."""
    remaining: list[tuple[str, str]] = []
    if influxdb:
        _, result = read_influxdb_status(runner, influxdb)
        if result.returncode == 0:
            remaining.append(("InfluxDB instance", influxdb))
        elif not is_missing_resource(result):
            print(f"Could not verify InfluxDB deletion: {failure_detail(result)}")
            remaining.append(("InfluxDB instance presence unknown", influxdb))
    if content_bucket:
        bucket_exists = read_bucket_presence(runner, content_bucket, account)
        if bucket_exists is True:
            remaining.append(("content bucket", content_bucket))
        elif bucket_exists is None:
            remaining.append(("content bucket presence unknown", content_bucket))
    stack_exists = read_stack_presence(runner)
    if stack_exists is True:
        remaining.append(("CloudFormation stack", STACK))
    elif stack_exists is None:
        remaining.append(("CloudFormation stack presence unknown", STACK))
    log_groups = read_lambda_log_groups(runner)
    if log_groups is None:
        remaining.append(("Lambda log groups presence unknown", f"/aws/lambda/{STACK}-*"))
    else:
        remaining.extend(("Lambda log group", name) for name in log_groups)
    artifacts_exist = read_bucket_presence(runner, artifact_bucket, account)
    if artifacts_exist is True:
        remaining.append(("deployment artifact bucket", artifact_bucket))
    elif artifacts_exist is None:
        remaining.append(("deployment artifact bucket presence unknown", artifact_bucket))
    return remaining


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


def print_teardown_timing(phases: Sequence[tuple[str, float]], total_seconds: float) -> None:
    """Make slow AWS-managed cleanup visible in tester output."""
    details = "; ".join(f"{name}: {seconds:.1f}s" for name, seconds in phases)
    details = details or "no managed-resource waits"
    print(f"Teardown timing — {details}; total: {total_seconds:.1f}s.")


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
    artifacts = os.environ.get("CMCD_ARTIFACTS_BUCKET") or artifact_bucket_name(account)
    artifacts_exist = read_bucket_presence(runner, artifacts, account)
    if artifacts_exist is None:
        print(f"Could not read deployment artifact bucket {artifacts}; nothing was deleted.")
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
    if not stack_exists and not log_groups and not artifacts_exist:
        print(
            f"Stack {STACK}, its deployment artifact bucket, and its stack-prefixed "
            "Lambda log groups are already absent."
        )
        return 0
    details = {
        "InfluxDB instance (deleted first)": influxdb or "already absent",
        "content bucket (emptied)": bucket or "already absent",
        "stack (deleted)": STACK if stack_exists else "already absent",
        "log groups (deleted)": ", ".join(log_groups) or "none",
        "deployment artifact bucket (deleted)": artifacts if artifacts_exist else "already absent",
    }
    prompt = ConfirmationPrompt(DESTROY_ACTION, STACK, REGION, account, details)
    if not ask_to_continue(prompt, assume_yes=assume_yes, ask=ask):
        return 1
    teardown_started = monotonic()
    phase_timings: list[tuple[str, float]] = []
    if influxdb:
        phase_started = monotonic()
        status = delete_influxdb_if_present(
            runner,
            influxdb,
            sleep=sleep,
            monotonic=monotonic,
        )
        phase_timings.append(("InfluxDB deletion", monotonic() - phase_started))
    else:
        status = 0
    if status == 0 and bucket:
        status = empty_bucket_if_present(runner, bucket)
    if status == 0 and stack_exists:
        phase_started = monotonic()
        status = delete_stack_if_present(runner)
        phase_timings.append(
            ("CloudFormation deletion (includes VPC ENI release)", monotonic() - phase_started)
        )
    if status != UNSAFE_LOOKUP_STATUS:
        delete_log_groups_if_present(runner, log_groups)
        if artifacts_exist:
            delete_artifact_bucket_if_present(runner, artifacts, account)
    remaining = find_remaining_resources(
        runner,
        account,
        influxdb=influxdb,
        content_bucket=bucket,
        artifact_bucket=artifacts,
    )
    print_teardown_timing(phase_timings, monotonic() - teardown_started)
    if remaining:
        print_remaining_resources(remaining)
        return 1
    print(
        f"Teardown complete for {STACK}: retained InfluxDB instance, content, stack, "
        f"deployment artifacts, and {len(log_groups)} log group(s) are absent.\n"
        "KMS keys created by the stack are scheduled for deletion by AWS (7-30 days); "
        "no action needed."
    )
    return 0
