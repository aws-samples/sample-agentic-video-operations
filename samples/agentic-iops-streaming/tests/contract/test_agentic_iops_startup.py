"""Deployed startup reads the signing key from its secret; bad settings fail in one line."""

from types import SimpleNamespace

import pytest

from agentic_iops_streaming.bootstrap.export_approval_signing_key import export_approval_signing_key
from agentic_iops_streaming.entrypoints import handle_agentcore_invocation as entrypoint
from agentic_iops_streaming.settings.runtime_settings import AgenticIopsSettings

SECRET_ARN = "arn:aws:secretsmanager:us-west-2:111122223333:secret:agentic-iops-key-AbCdEf"


class FakeSecrets:
    def __init__(self):
        self.reads = []

    def get_secret_value(self, SecretId):
        self.reads.append(SecretId)
        return {"SecretString": "shared-key"}


def test_the_secret_arn_becomes_the_shared_signing_key():
    secrets = FakeSecrets()
    environ = {"APPROVAL_SIGNING_KEY_SECRET_ARN": SECRET_ARN, "AWS_REGION": "us-west-2"}

    export_approval_signing_key(environ, create_client=lambda *a, **k: secrets)

    assert environ["APPROVAL_SIGNING_KEY"] == "shared-key"
    assert secrets.reads == [SECRET_ARN]


def test_an_explicit_key_wins_and_no_secret_is_read():
    environ = {"APPROVAL_SIGNING_KEY_SECRET_ARN": SECRET_ARN, "APPROVAL_SIGNING_KEY": "local"}

    export_approval_signing_key(environ, create_client=lambda *a, **k: pytest.fail("read"))

    assert environ["APPROVAL_SIGNING_KEY"] == "local"


def test_a_settings_error_is_one_line_without_values(monkeypatch, capsys):
    def invalid_settings():
        AgenticIopsSettings(memory_id="memory-1", approval_signing_key="")

    monkeypatch.setattr(entrypoint, "get_agentic_iops", invalid_settings)

    with pytest.raises(SystemExit) as exited:
        entrypoint.main()

    error = capsys.readouterr().err.splitlines()
    assert exited.value.code == 2
    assert error[0].startswith(
        "agentic-iops-streaming cannot start: settings: Value error, MEMORY_ID"
    )
    assert error[1].startswith("Fix the reported AgentCore deployment setting")
    assert "root .env" not in "\n".join(error)
    assert "just run" not in "\n".join(error)
    assert "Traceback" not in "\n".join(error)
    assert "memory-1" not in "\n".join(error)


def test_a_missing_model_is_reported_with_its_next_action(monkeypatch, capsys):
    def no_model():
        raise RuntimeError("AGENT_MODEL_ID is not set. Set it in the root .env or the CDK stack.")

    monkeypatch.setattr(entrypoint, "get_agentic_iops", no_model)

    with pytest.raises(SystemExit):
        entrypoint.main()

    assert "AGENT_MODEL_ID is not set" in capsys.readouterr().err


def test_a_local_startup_error_points_to_the_clone_configuration(monkeypatch, capsys):
    monkeypatch.setenv("AGENTIC_IOPS_LOCAL_MODE", "true")
    monkeypatch.setattr(
        entrypoint,
        "get_agentic_iops",
        lambda: (_ for _ in ()).throw(RuntimeError("bad local setting")),
    )

    with pytest.raises(SystemExit):
        entrypoint.main()

    error = capsys.readouterr().err
    assert "root .env" in error
    assert "just run agentic-iops-streaming" in error
    assert "just deploy" not in error


def test_main_runs_agentcore_on_the_configured_port(monkeypatch):
    settings = AgenticIopsSettings(agentic_iops_port=8091)
    ports = []
    monkeypatch.setattr(entrypoint, "get_agentic_iops", lambda: SimpleNamespace(settings=settings))
    monkeypatch.setattr(entrypoint.app, "run", lambda *, port: ports.append(port))

    entrypoint.main()

    assert ports == [8091]


def test_the_agentic_iops_samples_a_shorter_visual_quality_window_unless_set():
    from agentic_iops_streaming.bootstrap.apply_agentic_iops_tool_defaults import (
        apply_agentic_iops_tool_defaults,
    )

    environ = {}
    apply_agentic_iops_tool_defaults(environ)
    assert environ == {"VISUAL_QUALITY_FRAMES": "8", "VISUAL_QUALITY_WINDOW_SECONDS": "20"}
    explicit = {"VISUAL_QUALITY_WINDOW_SECONDS": "40"}
    apply_agentic_iops_tool_defaults(explicit)
    assert explicit["VISUAL_QUALITY_WINDOW_SECONDS"] == "40"


@pytest.mark.parametrize("value", ["t", "y", "TRUE", "1", "on"])
def test_local_mode_is_read_as_the_settings_read_it(value):
    """The settings failed to load, so the hint parses the flag itself, as pydantic would."""
    assert "just run" in entrypoint.startup_recovery_step({"AGENTIC_IOPS_LOCAL_MODE": value})


@pytest.mark.parametrize("value", ["", "false", "0", "off", "not-a-boolean"])
def test_anything_else_gets_the_deployed_runtime_hint(value):
    assert "just deploy" in entrypoint.startup_recovery_step({"AGENTIC_IOPS_LOCAL_MODE": value})
