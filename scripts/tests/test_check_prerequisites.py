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


def test_aws_doctor_runs_live_read_probe_after_prerequisites_pass(monkeypatch, capsys):
    monkeypatch.setattr(
        doctor,
        "collect_results",
        lambda: [
            result(doctor.CheckGroup.OFFLINE, "python", True),
            result(doctor.CheckGroup.AWS, "credentials", True),
        ],
    )
    monkeypatch.setattr(
        doctor,
        "check_aws_read_paths",
        lambda: result(doctor.CheckGroup.AWS, "sample read paths", True),
    )

    assert doctor.main(["aws"]) == 0
    assert "ok   sample read paths" in capsys.readouterr().out


def test_aws_doctor_skips_live_probe_when_a_prerequisite_fails(monkeypatch):
    monkeypatch.setattr(
        doctor,
        "collect_results",
        lambda: [result(doctor.CheckGroup.AWS, "credentials", False)],
    )
    monkeypatch.setattr(
        doctor,
        "check_aws_read_paths",
        lambda: (_ for _ in ()).throw(AssertionError("probe must not run")),
    )

    assert doctor.main(["aws"]) == 1


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


def test_aws_doctor_names_each_failed_probe_line(monkeypatch):
    import subprocess

    import check_prerequisites

    stdout = (
        "ok   cmcd           a -> b\nFAIL medialive      list_channels   ToolCallFailed: denied\n"
    )
    monkeypatch.setattr(
        check_prerequisites,
        "run_command",
        lambda *command, timeout=30: subprocess.CompletedProcess(command, 1, stdout, ""),
    )

    result = check_prerequisites.check_aws_read_paths()

    assert not result.passed
    assert result.detail == "FAIL medialive list_channels ToolCallFailed: denied"
