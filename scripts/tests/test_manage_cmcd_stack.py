import subprocess

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
        self, *, account="111122223333", outputs=OUTPUTS, failing=(), log_groups=LOG_GROUPS
    ):
        self.account = account
        self.log_groups = log_groups
        self.outputs = outputs
        self.failing = failing
        self.calls = []

    def __call__(self, arguments, capture):
        self.calls.append(list(arguments))
        joined = " ".join(arguments)
        if any(fragment in joined for fragment in self.failing):
            return subprocess.CompletedProcess(arguments, 255, "", "error")
        if "get-caller-identity" in joined:
            return self._answer(self.account)
        if "describe-log-groups" in joined:  # the CLI exits 0 with empty output for no groups
            return subprocess.CompletedProcess(arguments, 0, "\t".join(self.log_groups) + "\n", "")
        if "describe-stacks" in joined:
            key = next((key for key in self.outputs if f"'{key}'" in joined), None)
            return self._answer(self.outputs.get(key) if key else None)
        return subprocess.CompletedProcess(arguments, 0, "", "")

    @staticmethod
    def _answer(value):
        if value is None:
            return subprocess.CompletedProcess([], 255, "", "not found")
        return subprocess.CompletedProcess([], 0, f"{value}\n", "")

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


def run(fake_aws, *argv, answer="n"):
    ask = FakeAsk(fake_aws, answer)
    return manage_cmcd_stack.main(list(argv), runner=fake_aws, ask=ask), ask


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
    prompt_text = capsys.readouterr().out.split("Deleted stack")[0]
    for listed in ("cmcd-content-111122223333", "video-ops-cmcd", "influx-demo", *LOG_GROUPS):
        assert listed in prompt_text
    lookups = ("describe-stacks", "get-caller-identity", "describe-log-groups")
    calls_before_prompt = fake_aws.calls[: ask.calls_before_prompt]
    assert all(any(lookup in call for lookup in lookups) for call in calls_before_prompt)


def test_destroy_deletes_stack_then_influxdb_then_each_log_group():
    fake_aws = FakeAws()
    status, ask = run(fake_aws, "destroy", answer="y")
    assert status == 0
    deletions = [call[:2] for call in fake_aws.calls[ask.calls_before_prompt :]]
    assert deletions == [
        ["s3", "rm"],
        ["cloudformation", "delete-stack"],
        ["cloudformation", "wait"],
        ["timestream-influxdb", "delete-db-instance"],
        ["logs", "delete-log-group"],
        ["logs", "delete-log-group"],
    ]
    [influx] = fake_aws.commands("delete-db-instance")
    assert influx[influx.index("--identifier") + 1] == "influx-demo"
    deleted_groups = [call[-1] for call in fake_aws.commands("delete-log-group")]
    assert deleted_groups == LOG_GROUPS


def test_destroy_without_log_groups_still_deletes_influxdb(capsys):
    fake_aws = FakeAws(log_groups=[])
    status, _ = run(fake_aws, "destroy", "--yes")
    assert status == 0
    assert "log groups (deleted): none" in capsys.readouterr().out
    assert len(fake_aws.commands("delete-db-instance")) == 1
    assert fake_aws.commands("delete-log-group") == []


def test_failed_influxdb_deletion_is_reported_and_stops_before_log_groups():
    fake_aws = FakeAws(failing=("delete-db-instance",))
    status, _ = run(fake_aws, "destroy", "--yes")
    assert status == 255
    assert fake_aws.commands("delete-log-group") == []


def test_declined_destroy_deletes_nothing():
    fake_aws = FakeAws()
    status, _ = run(fake_aws, "destroy", answer="n")
    assert status == 1
    for deletion in ("delete-stack", "s3 rm", "delete-db-instance", "delete-log-group"):
        assert fake_aws.commands(deletion) == []


def test_destroy_of_a_missing_stack_deletes_nothing():
    fake_aws = FakeAws(outputs={})
    status, ask = run(fake_aws, "destroy", answer="y")
    assert status == 1
    assert ask.calls_before_prompt is None
    assert fake_aws.commands("delete-stack") == []


def test_destroy_stops_at_the_first_failed_step():
    fake_aws = FakeAws(failing=("s3 rm",))
    status, _ = run(fake_aws, "destroy", "--yes")
    assert status == 255
    assert fake_aws.commands("delete-stack") == []


def test_destroy_tells_how_to_check_the_influxdb_deletion(capsys):
    run(FakeAws(), "destroy", "--yes")
    assert "get-db-instance --region us-east-1 --identifier influx-demo" in capsys.readouterr().out


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
