import check_prerequisites as doctor


def result(group, name, passed, fix="fix command"):
    return doctor.CheckResult(group, name, passed, "detail", fix)


def test_plain_doctor_warns_for_aws_failures_without_failing(monkeypatch, capsys):
    monkeypatch.setattr(
        doctor,
        "collect_results",
        lambda: [
            result(doctor.CheckGroup.OFFLINE, "python", True),
            result(doctor.CheckGroup.AWS, "docker", False),
        ],
    )

    assert doctor.main([]) == 0
    output = capsys.readouterr().out
    assert "WARN docker" in output
    assert "fix: fix command" in output
    assert "Offline development is ready" in output


def test_plain_doctor_fails_when_an_offline_requirement_is_missing(monkeypatch, capsys):
    monkeypatch.setattr(
        doctor,
        "collect_results",
        lambda: [
            result(doctor.CheckGroup.OFFLINE, "just", False),
            result(doctor.CheckGroup.AWS, "aws", False),
        ],
    )

    assert doctor.main([]) == 1
    output = capsys.readouterr().out
    assert "FAIL just" in output
    assert "WARN aws" in output


def test_aws_doctor_makes_deployment_checks_strict(monkeypatch, capsys):
    monkeypatch.setattr(
        doctor,
        "collect_results",
        lambda: [
            result(doctor.CheckGroup.OFFLINE, "python", True),
            result(doctor.CheckGroup.AWS, "cdk bootstrap", False),
        ],
    )

    assert doctor.main(["aws"]) == 1
    assert "FAIL cdk bootstrap" in capsys.readouterr().out


def test_aws_group_checks_npx_instead_of_a_global_cdk(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: None)
    monkeypatch.delenv("AWS_REGION", raising=False)

    results = doctor.collect_aws_results()

    names = {item.name for item in results}
    assert {
        "aws",
        "session-manager-plugin",
        "docker",
        "node",
        "npx",
        "cdk bootstrap",
    } <= names
    assert "cdk" not in names
    assert all(item.fix for item in results if not item.passed)


def test_unset_model_is_reported_without_an_aws_call(monkeypatch):
    monkeypatch.delenv("AGENT_MODEL_ID", raising=False)

    def refuse(*_args):
        raise AssertionError("model lookup should not run without a configured model")

    monkeypatch.setattr(doctor, "run_command", refuse)

    result = doctor.check_model_access("AGENT_MODEL_ID", "us-west-2")

    assert not result.passed
    assert result.detail == "not set"
    assert result.fix == "cp .env.example .env  # then set AGENT_MODEL_ID"


def test_python_312_or_newer_is_an_offline_requirement(monkeypatch):
    monkeypatch.setattr(doctor.sys, "version_info", (3, 11, 9))
    old_python = doctor.check_python_version()
    monkeypatch.setattr(doctor.sys, "version_info", (3, 12, 0))
    supported_python = doctor.check_python_version()

    assert not old_python.passed
    assert supported_python.passed


def test_command_timeout_becomes_a_failed_check_result(monkeypatch):
    def time_out(*_args, **_kwargs):
        raise doctor.subprocess.TimeoutExpired(("aws", "sts"), 30)

    monkeypatch.setattr(doctor.subprocess, "run", time_out)

    result = doctor.run_command("aws", "sts")

    assert result.returncode == 124
    assert result.stderr == "timed out"
