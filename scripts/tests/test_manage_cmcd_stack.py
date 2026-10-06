import json
import subprocess
from pathlib import Path

import destroy_cmcd_stack
import manage_cmcd_stack
import pytest

OUTPUTS = {
    "BastionHostInstanceId": "i-0demo",
    "InfluxDBEndpoint": "demo.timestream-influxdb.us-east-1.on.aws",
    "InfluxDBSecretArn": "arn:aws:secretsmanager:us-east-1:111122223333:secret:demo",
    "VideoPlayerURL": "https://d111.cloudfront.net/index.html",
    "S3BucketName": "cmcd-content-111122223333",
    "InfluxDBInstanceId": "influx-demo",
}

LOG_GROUPS = [
    "/aws/lambda/video-ops-cmcd-update-secret",
    "/aws/lambda/video-ops-cmcd-secret-rotation",
]


class FakeAws:
    """Records every AWS CLI call and answers lookups from canned values."""

    def __init__(
        self,
        *,
        account="111122223333",
        outputs=OUTPUTS,
        failing=(),
        fail_once=(),
        log_groups=LOG_GROUPS,
        influx_statuses=("AVAILABLE", None),
        bucket_exists=True,
        stack_status="auto",
        physical_resources=None,
        failure_messages=None,
    ):
        self.account = account
        self.log_groups = list(log_groups)
        self.outputs = dict(outputs)
        self.failing = failing
        self.failure_messages = failure_messages or {}
        self.fail_once = fail_once
        self.failed_once = set()
        self.influx_statuses = list(influx_statuses)
        self.bucket_exists = bucket_exists
        self.stack_status = (
            ("CREATE_COMPLETE" if self.outputs else None)
            if stack_status == "auto"
            else stack_status
        )
        self.physical_resources = physical_resources or {
            "InfluxDBInstance": "influx-demo",
            "ContentBucket": "cmcd-content-111122223333",
        }
        self.calls = []
        self.secret = {
            "username": "admin",
            "password": "password-secret",
            "organization": "cmcd-org",
            "bucket": "cmcd-metrics",
            "token": "operator-token-secret",
        }

    def __call__(self, arguments, capture):
        self.calls.append(list(arguments))
        joined = " ".join(arguments)
        if any(fragment in joined for fragment in self.failing):
            message = next(
                (
                    message
                    for fragment, message in self.failure_messages.items()
                    if fragment in joined
                ),
                "error",
            )
            return subprocess.CompletedProcess(arguments, 255, "", message)
        one_time_failure = next(
            (
                fragment
                for fragment in self.fail_once
                if fragment in joined and fragment not in self.failed_once
            ),
            None,
        )
        if one_time_failure:
            self.failed_once.add(one_time_failure)
            return subprocess.CompletedProcess(arguments, 255, "", "error")
        if "get-caller-identity" in joined:
            return self._answer(self.account)
        if "describe-log-groups" in joined:  # the CLI exits 0 with empty output for no groups
            return subprocess.CompletedProcess(arguments, 0, "\t".join(self.log_groups) + "\n", "")
        if "get-db-instance" in joined:
            status = self.influx_statuses[0]
            if len(self.influx_statuses) > 1:
                self.influx_statuses.pop(0)
            if isinstance(status, tuple):
                return subprocess.CompletedProcess(arguments, 255, "", status[1])
            if status is None:
                return self._missing(arguments, "ResourceNotFoundException")
            return self._answer(status)
        if "head-bucket" in joined:
            if not self.bucket_exists:
                return self._missing(arguments, "404 Not Found")
            return subprocess.CompletedProcess(arguments, 0, "", "")
        if "s3 rm" in joined:
            self.bucket_exists = False
        if "cloudformation delete-stack" in joined:
            self.stack_status = None
        if "delete-log-group" in joined:
            self.log_groups = [name for name in self.log_groups if name != arguments[-1]]
        if "describe-stacks" in joined:
            if "StackStatus" in joined:
                if self.stack_status is None:
                    return self._missing(arguments, "StackNotFound")
                return self._answer(self.stack_status)
            key = next((key for key in self.outputs if f"'{key}'" in joined), None)
            return self._answer(self.outputs.get(key) if key else None)
        if "describe-stack-resource" in joined:
            logical_id = arguments[arguments.index("--logical-resource-id") + 1]
            return self._answer(self.physical_resources.get(logical_id))
        if "get-secret-value" in joined:
            return self._answer(json.dumps(self.secret))
        return subprocess.CompletedProcess(arguments, 0, "", "")

    @staticmethod
    def _answer(value):
        if value is None:
            return subprocess.CompletedProcess([], 255, "", "not found")
        return subprocess.CompletedProcess([], 0, f"{value}\n", "")

    @staticmethod
    def _missing(arguments, message):
        if message == "StackNotFound":
            detail = (
                "An error occurred (ValidationError) when calling DescribeStacks: "
                "Stack with id video-ops-cmcd does not exist"
            )
        else:
            error_code = "404" if message == "404 Not Found" else message
            detail = f"An error occurred ({error_code}) when calling an AWS operation"
        return subprocess.CompletedProcess(arguments, 255, "", detail)

    def commands(self, verb):
        return [call for call in self.calls if verb in " ".join(call)]


class FakeAsk:
    def __init__(self, fake_aws, answer):
        self.fake_aws = fake_aws
        self.answer = answer
        self.calls_before_prompt = None

    def __call__(self, _prompt):
        self.calls_before_prompt = len(self.fake_aws.calls)
        return self.answer


def run(
    fake_aws,
    *argv,
    answer="n",
    token_creator=manage_cmcd_stack.create_influxdb_read_token,
    env_path=Path(".env"),
    env_example_path=Path(".env.example"),
):
    ask = FakeAsk(fake_aws, answer)
    return (
        manage_cmcd_stack.main(
            list(argv),
            runner=fake_aws,
            ask=ask,
            token_creator=token_creator,
            env_path=env_path,
            env_example_path=env_example_path,
        ),
        ask,
    )


def test_deploy_with_yes_deploys_the_template_in_us_east_1_and_prints_next_steps(capsys):
    fake_aws = FakeAws()
    status, _ = run(fake_aws, "deploy", "--yes")
    assert status == 0
    [deploy] = fake_aws.commands("cloudformation deploy")
    assert deploy[deploy.index("--region") + 1] == "us-east-1"
    assert deploy[deploy.index("--stack-name") + 1] == "video-ops-cmcd"
    assert "S3BucketName=cmcd-content-111122223333" in deploy
    assert "OriginDomainName=example.com" in deploy
    output = capsys.readouterr().out
    assert "--target i-0demo" in output
    assert "VERIFY_SSL=false" in output
    assert 'json.load(sys.stdin)["password"]' in output
    assert "--query SecretString --output text\n" not in output


def test_deploy_uses_bucket_and_origin_from_the_environment(monkeypatch):
    monkeypatch.setenv("CMCD_S3_BUCKET_NAME", "my-bucket")
    monkeypatch.setenv("CMCD_ORIGIN_DOMAIN", "origin.example.org")
    fake_aws = FakeAws()
    run(fake_aws, "deploy", "--yes")
    [deploy] = fake_aws.commands("cloudformation deploy")
    assert "S3BucketName=my-bucket" in deploy
    assert "OriginDomainName=origin.example.org" in deploy


def test_declined_deploy_makes_no_cloudformation_call():
    fake_aws = FakeAws()
    status, _ = run(fake_aws, "deploy", answer="n")
    assert status == 1
    assert fake_aws.commands("cloudformation deploy") == []


def test_deploy_without_credentials_stops_before_asking():
    fake_aws = FakeAws(account=None)
    status, ask = run(fake_aws, "deploy", answer="y")
    assert status == 1
    assert ask.calls_before_prompt is None
    assert fake_aws.commands("cloudformation deploy") == []


def test_failed_deploy_returns_its_exit_code_and_skips_next_steps():
    fake_aws = FakeAws(failing=("cloudformation deploy",))
    status, _ = run(fake_aws, "deploy", "--yes")
    assert status == 255
    assert fake_aws.commands("BastionHostInstanceId") == []


def test_destroy_prompt_lists_bucket_stack_influxdb_and_log_groups_before_deleting(capsys):
    fake_aws = FakeAws()
    status, ask = run(fake_aws, "destroy", answer="y")
    assert status == 0
    prompt_text = capsys.readouterr().out.split("Teardown complete")[0]
    for listed in ("cmcd-content-111122223333", "video-ops-cmcd", "influx-demo", *LOG_GROUPS):
        assert listed in prompt_text
    lookups = ("describe-stacks", "get-caller-identity", "describe-log-groups")
    calls_before_prompt = fake_aws.calls[: ask.calls_before_prompt]
    assert all(any(lookup in call for lookup in lookups) for call in calls_before_prompt)


def test_destroy_deletes_influxdb_before_bucket_stack_and_log_groups():
    fake_aws = FakeAws()
    status, ask = run(fake_aws, "destroy", answer="y")
    assert status == 0
    actions = [" ".join(call[:2]) for call in fake_aws.calls[ask.calls_before_prompt :]]
    assert actions == [
        "timestream-influxdb get-db-instance",
        "timestream-influxdb delete-db-instance",
        "timestream-influxdb get-db-instance",
        "s3api head-bucket",
        "s3 rm",
        "cloudformation delete-stack",
        "cloudformation wait",
        "logs delete-log-group",
        "logs delete-log-group",
    ]
    [influx] = fake_aws.commands("delete-db-instance")
    assert influx[influx.index("--identifier") + 1] == "influx-demo"
    [empty_bucket] = fake_aws.commands("s3 rm")
    assert "--only-show-errors" in empty_bucket
    deleted_groups = [call[-1] for call in fake_aws.commands("delete-log-group")]
    assert deleted_groups == LOG_GROUPS


def test_destroy_without_log_groups_still_deletes_influxdb(capsys):
    fake_aws = FakeAws(log_groups=[])
    status, _ = run(fake_aws, "destroy", "--yes")
    assert status == 0
    assert "log groups (deleted): none" in capsys.readouterr().out
    assert len(fake_aws.commands("delete-db-instance")) == 1
    assert fake_aws.commands("delete-log-group") == []


def test_failed_influxdb_deletion_still_cleans_log_groups_and_reports_remaining(capsys):
    fake_aws = FakeAws(failing=("delete-db-instance",))
    status, _ = run(fake_aws, "destroy", "--yes")
    assert status == 1
    assert fake_aws.commands("s3 rm") == []
    assert fake_aws.commands("delete-stack") == []
    assert len(fake_aws.commands("delete-log-group")) == len(LOG_GROUPS)
    output = capsys.readouterr().out
    assert "InfluxDB instance or deletion status unknown: influx-demo" in output
    assert "content bucket: cmcd-content-111122223333" in output
    assert "CloudFormation stack: video-ops-cmcd" in output


def test_declined_destroy_deletes_nothing():
    fake_aws = FakeAws()
    status, _ = run(fake_aws, "destroy", answer="n")
    assert status == 1
    for deletion in ("delete-stack", "s3 rm", "delete-db-instance", "delete-log-group"):
        assert fake_aws.commands(deletion) == []


def test_destroy_of_a_missing_stack_deletes_nothing():
    fake_aws = FakeAws(outputs={}, log_groups=[])
    status, ask = run(fake_aws, "destroy", answer="y")
    assert status == 0
    assert ask.calls_before_prompt is None
    assert fake_aws.commands("delete-stack") == []


def test_destroy_does_not_treat_a_failed_stack_lookup_as_already_absent(capsys):
    fake_aws = FakeAws(failing=("StackStatus",), log_groups=[])
    status, ask = run(fake_aws, "destroy", answer="y")
    assert status == 1
    assert ask.calls_before_prompt is None
    assert fake_aws.commands("delete-stack") == []
    assert "nothing was deleted" in capsys.readouterr().out.lower()


def test_destroy_skips_dependent_stack_after_bucket_failure_but_cleans_logs(capsys):
    fake_aws = FakeAws(failing=("s3 rm",))
    status, _ = run(fake_aws, "destroy", "--yes")
    assert status == 1
    assert fake_aws.commands("delete-stack") == []
    assert len(fake_aws.commands("delete-log-group")) == len(LOG_GROUPS)
    output = capsys.readouterr().out
    assert "content bucket: cmcd-content-111122223333" in output
    assert "CloudFormation stack: video-ops-cmcd" in output
    assert "InfluxDB instance or deletion status unknown" not in output


def test_destroy_second_run_converges_after_partial_failure():
    fake_aws = FakeAws(fail_once=("s3 rm",))

    first_status, _ = run(fake_aws, "destroy", "--yes")
    second_status, _ = run(fake_aws, "destroy", "--yes")

    assert first_status == 1
    assert second_status == 0
    assert len(fake_aws.commands("delete-db-instance")) == 1
    assert len(fake_aws.commands("delete-stack")) == 1
    assert len(fake_aws.commands("delete-log-group")) == len(LOG_GROUPS)


def test_destroy_second_run_cleans_logs_after_stack_delete_wait_fails():
    fake_aws = FakeAws(fail_once=("cloudformation wait",))

    first_status, _ = run(fake_aws, "destroy", "--yes")
    second_status, _ = run(fake_aws, "destroy", "--yes")

    assert first_status == 1
    assert second_status == 0
    assert len(fake_aws.commands("delete-stack")) == 1
    assert len(fake_aws.commands("delete-log-group")) == len(LOG_GROUPS)


def test_influxdb_wait_stops_at_its_bounded_deadline(capsys):
    fake_aws = FakeAws(influx_statuses=("DELETING",))
    now = 0.0

    def monotonic():
        return now

    def sleep(seconds):
        nonlocal now
        now += seconds

    status = destroy_cmcd_stack.wait_for_influxdb_deletion(
        fake_aws,
        "influx-demo",
        sleep=sleep,
        monotonic=monotonic,
        timeout_seconds=30,
    )

    assert status == 1
    assert len(fake_aws.commands("get-db-instance")) == 3
    assert "Timed out after 30s" in capsys.readouterr().out


def test_destroy_skips_an_already_missing_bucket():
    fake_aws = FakeAws(bucket_exists=False)
    status, _ = run(fake_aws, "destroy", "--yes")
    assert status == 0
    assert fake_aws.commands("s3 rm") == []
    assert len(fake_aws.commands("delete-stack")) == 1


def test_destroy_uses_stack_resources_when_rollback_has_no_outputs():
    fake_aws = FakeAws(outputs={}, stack_status="ROLLBACK_COMPLETE")

    status, _ = run(fake_aws, "destroy", "--yes")

    assert status == 0
    logical_ids = [
        call[call.index("--logical-resource-id") + 1]
        for call in fake_aws.commands("describe-stack-resource")
    ]
    assert logical_ids == ["InfluxDBInstance", "ContentBucket"]
    assert len(fake_aws.commands("delete-db-instance")) == 1
    assert len(fake_aws.commands("s3 rm")) == 1
    assert len(fake_aws.commands("delete-stack")) == 1


def test_access_denied_influxdb_lookup_is_not_mistaken_for_account_404(capsys):
    denied = (
        "An error occurred (AccessDeniedException) when calling GetDbInstance: "
        "not authorized for arn:aws:timestream-influxdb:us-east-1:123404567890:db/influx-demo"
    )
    fake_aws = FakeAws(
        failing=("get-db-instance",),
        failure_messages={"get-db-instance": denied},
    )

    status, _ = run(fake_aws, "destroy", "--yes")

    assert status == 1
    for deletion in ("delete-db-instance", "s3 rm", "delete-stack", "delete-log-group"):
        assert fake_aws.commands(deletion) == []
    output = capsys.readouterr().out
    assert "AccessDeniedException" in output
    assert "InfluxDB instance or deletion status unknown: influx-demo" in output


def test_access_denied_influxdb_wait_poll_stops_without_dependent_deletes(capsys):
    denied = (
        "An error occurred (AccessDeniedException) when calling GetDbInstance: "
        "not authorized for arn:aws:timestream-influxdb:us-east-1:123404567890:db/influx-demo"
    )
    fake_aws = FakeAws(influx_statuses=("DELETING", ("error", denied)))

    status, _ = run(fake_aws, "destroy", "--yes")

    assert status == 1
    for deletion in ("delete-db-instance", "s3 rm", "delete-stack", "delete-log-group"):
        assert fake_aws.commands(deletion) == []
    output = capsys.readouterr().out
    assert "AccessDeniedException" in output
    assert "InfluxDB instance or deletion status unknown: influx-demo" in output


def test_log_group_failures_do_not_skip_other_groups_and_report_only_failed_group(capsys):
    failed_group = LOG_GROUPS[0]
    fake_aws = FakeAws(failing=(failed_group,))

    status, _ = run(fake_aws, "destroy", "--yes")

    assert status == 1
    assert len(fake_aws.commands("delete-log-group")) == len(LOG_GROUPS)
    remaining = capsys.readouterr().out.split("Teardown incomplete. Remaining resources:", 1)[1]
    assert f"Lambda log group: {failed_group}" in remaining
    assert LOG_GROUPS[1] not in remaining
    assert "CloudFormation stack:" not in remaining


@pytest.mark.parametrize("command", ["deploy", "destroy"])
def test_unknown_flags_are_rejected(command):
    with pytest.raises(SystemExit):
        manage_cmcd_stack.main([command, "--force"], runner=FakeAws())


def test_destroy_aborts_before_asking_when_log_groups_cannot_be_listed(capsys):
    fake_aws = FakeAws(failing=("describe-log-groups",))
    status, ask = run(fake_aws, "destroy", answer="y")
    assert status == 1
    assert ask.calls_before_prompt is None
    for deletion in ("s3 rm", "delete-stack", "delete-db-instance", "delete-log-group"):
        assert fake_aws.commands(deletion) == []
    assert "Nothing was deleted" in capsys.readouterr().out


def test_declined_read_token_creation_does_not_read_secret_or_write_env(tmp_path):
    fake_aws = FakeAws()
    env_path = tmp_path / ".env"

    status, _ = run(
        fake_aws,
        "create-read-token",
        answer="n",
        token_creator=lambda *_args: pytest.fail("token API must not be called"),
        env_path=env_path,
        env_example_path=tmp_path / ".env.example",
    )

    assert status == 1
    assert fake_aws.commands("get-secret-value") == []
    assert not env_path.exists()


def test_read_token_creation_updates_root_env_without_echoing_secrets(tmp_path, capsys):
    fake_aws = FakeAws()
    env_path = tmp_path / ".env"
    env_path.write_text(
        "AWS_REGION=us-west-2\nINFLUXDB_TOKEN=old-token\nINFLUXDB_TOKEN=older-token\n"
    )
    received = []

    def create_token(url, credentials):
        received.append((url, credentials))
        return "read-token-secret"

    status, _ = run(
        fake_aws,
        "create-read-token",
        "--yes",
        token_creator=create_token,
        env_path=env_path,
        env_example_path=tmp_path / ".env.example",
    )

    assert status == 0
    assert received[0][0] == "https://localhost:8086"
    assert received[0][1].bucket == "cmcd-metrics"
    content = env_path.read_text()
    assert "AWS_REGION=us-west-2" in content
    assert "INFLUXDB_URL=https://localhost:8086" in content
    assert "INFLUXDB_ORG=cmcd-org" in content
    assert "INFLUXDB_TOKEN=read-token-secret" in content
    assert content.count("INFLUXDB_TOKEN=read-token-secret") == 1
    assert "old-token" not in content
    assert "VERIFY_SSL=false" in content
    assert env_path.stat().st_mode & 0o777 == 0o600
    output = capsys.readouterr().out
    for secret in ("password-secret", "operator-token-secret", "read-token-secret"):
        assert secret not in output
    assert output.strip() == "written"


def test_invalid_influxdb_secret_does_not_call_api_or_write_env(tmp_path, capsys):
    fake_aws = FakeAws()
    fake_aws.secret.pop("password")
    env_path = tmp_path / ".env"

    status, _ = run(
        fake_aws,
        "create-read-token",
        "--yes",
        token_creator=lambda *_args: pytest.fail("token API must not be called"),
        env_path=env_path,
        env_example_path=tmp_path / ".env.example",
    )

    assert status == 1
    assert not env_path.exists()
    assert "missing required fields" in capsys.readouterr().out
