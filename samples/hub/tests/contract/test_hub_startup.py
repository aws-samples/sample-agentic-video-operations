"""Deployed startup reads the signing key from its secret; bad settings fail in one line."""

import pytest

from media_ops_hub.bootstrap.export_approval_signing_key import export_approval_signing_key
from media_ops_hub.entrypoints import handle_agentcore_invocation as entrypoint
from media_ops_hub.settings.runtime_settings import HubSettings

SECRET_ARN = "arn:aws:secretsmanager:us-west-2:111122223333:secret:hub-key-AbCdEf"


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
        HubSettings(memory_id="memory-1", approval_signing_key="")

    monkeypatch.setattr(entrypoint, "get_hub", invalid_settings)

    with pytest.raises(SystemExit) as exited:
        entrypoint.main()

    error = capsys.readouterr().err.splitlines()
    assert exited.value.code == 2
    assert error[0].startswith("media-ops-hub cannot start: settings: Value error, MEMORY_ID")
    assert "Traceback" not in "\n".join(error)
    assert "memory-1" not in "\n".join(error)


def test_a_missing_model_is_reported_with_its_next_action(monkeypatch, capsys):
    def no_model():
        raise RuntimeError("AGENT_MODEL_ID is not set. Set it in the root .env or the CDK stack.")

    monkeypatch.setattr(entrypoint, "get_hub", no_model)

    with pytest.raises(SystemExit):
        entrypoint.main()

    assert "AGENT_MODEL_ID is not set" in capsys.readouterr().err


def test_the_hub_samples_a_shorter_visual_quality_window_unless_set():
    from media_ops_hub.bootstrap.apply_hub_tool_defaults import apply_hub_tool_defaults

    environ = {}
    apply_hub_tool_defaults(environ)
    assert environ == {"VISUAL_QUALITY_FRAMES": "8", "VISUAL_QUALITY_WINDOW_SECONDS": "20"}
    explicit = {"VISUAL_QUALITY_WINDOW_SECONDS": "40"}
    apply_hub_tool_defaults(explicit)
    assert explicit["VISUAL_QUALITY_WINDOW_SECONDS"] == "40"
