import subprocess
from pathlib import Path

import manage_hydrolix_stack
import pytest

SETTINGS = {
    "AWS_REGION": "us-west-2",
    "AGENT_MODEL_ID": "us.anthropic.claude-sonnet-4-6",
    "HYDROLIX_TABLE": "video.cmcd",
}


class FakeRunner:
    def __init__(self, *, account="111122223333", failing=(), missing=()):
        self.account = account
        self.failing = failing
        self.missing = missing
        self.calls = []

    def __call__(self, arguments, cwd, capture):
        call = (list(arguments), cwd, capture)
        self.calls.append(call)
        joined = " ".join(arguments)
        if any(fragment in joined for fragment in self.failing):
            return subprocess.CompletedProcess(arguments, 9, "", "failed")
        if any(fragment in joined for fragment in self.missing):
            return subprocess.CompletedProcess(arguments, 254, "", "NotFoundException")
        if "get-caller-identity" in joined:
            status = 0 if self.account else 1
            return subprocess.CompletedProcess(arguments, status, f"{self.account or ''}\n", "")
        if arguments[:2] == ["git", "clone"]:
            package = Path(arguments[-1]) / "mcp_hydrolix"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text("")
        return subprocess.CompletedProcess(arguments, 0, "", "")

    def matching(self, fragment):
        return [arguments for arguments, _, _ in self.calls if fragment in " ".join(arguments)]


def isolate_paths(monkeypatch, tmp_path):
    cdk = tmp_path / "cdk"
    destination = cdk / "agent" / "src" / "mcp" / "mcp_hydrolix"
    monkeypatch.setattr(manage_hydrolix_stack, "CDK_DIRECTORY", cdk)
    monkeypatch.setattr(manage_hydrolix_stack, "CDK_EXECUTABLE", cdk / "node_modules/.bin/cdk")
    monkeypatch.setattr(manage_hydrolix_stack, "MCP_DESTINATION", destination)
    return destination


def test_cdk_directory_exists_in_the_repository():
    assert manage_hydrolix_stack.CDK_DIRECTORY.is_dir()
    assert (manage_hydrolix_stack.CDK_DIRECTORY / "package-lock.json").is_file()


def test_runtime_sources_take_model_ids_only_from_settings():
    agent_directory = manage_hydrolix_stack.AGENT_DIRECTORY
    runtime_sources = [
        agent_directory / "app.py",
        *(agent_directory / "src" / "tools").glob("*_agent.py"),
        manage_hydrolix_stack.REPOSITORY_ROOT
        / "samples"
        / "hydrolix"
        / "amplify-hydrolix-data-assistant-agentcore-strands"
        / "src"
        / "sample.env.js",
    ]

    for source in runtime_sources:
        content = source.read_text()
        assert "global.anthropic." not in content
        assert "us.anthropic." not in content
        assert "MODEL_ID_FOR_CHART" not in content


def test_docker_requirement_cannot_be_parsed_as_a_shell_redirect():
    dockerfile = (manage_hydrolix_stack.AGENT_DIRECTORY / "Dockerfile").read_text()

    assert 'uv pip install "aws-opentelemetry-distro>=0.10.1"' in dockerfile
    assert "uv pip install aws-opentelemetry-distro>=" not in dockerfile


def test_orchestrator_fallback_names_only_available_hydrolix_agents():
    app_source = (manage_hydrolix_stack.AGENT_DIRECTORY / "app.py").read_text()

    assert "video_games_sales_agent" not in app_source
    for agent in ("hydrolix_agent", "qoe_analysis_agent", "cache_origin_agent"):
        assert agent in app_source


def test_deploy_pins_mcp_source_and_passes_env_parameters(monkeypatch, tmp_path):
    destination = isolate_paths(monkeypatch, tmp_path)
    runner = FakeRunner()

    status = manage_hydrolix_stack.deploy_stack(
        runner,
        assume_yes=True,
        environ=SETTINGS,
        ask=lambda _: "n",
    )

    assert status == 0
    [checkout] = runner.matching("git checkout")
    assert manage_hydrolix_stack.MCP_COMMIT in checkout
    [deploy] = runner.matching("cdk deploy")
    assert "BedrockModelId=us.anthropic.claude-sonnet-4-6" in deploy
    assert "HydrolixTable=video.cmcd" in deploy
    assert deploy[-2:] == ["--require-approval", "never"]
    assert runner.matching("npm ci")
    assert (destination / "__init__.py").exists()


def test_interactive_deploy_keeps_cdks_broadening_approval(monkeypatch, tmp_path):
    isolate_paths(monkeypatch, tmp_path)
    runner = FakeRunner()

    status = manage_hydrolix_stack.deploy_stack(
        runner,
        assume_yes=False,
        environ=SETTINGS,
        ask=lambda _: "y",
    )

    assert status == 0
    [deploy] = runner.matching("cdk deploy")
    assert deploy[-2:] == ["--require-approval", "broadening"]


def test_deploy_stops_before_aws_when_a_setting_is_missing(capsys):
    runner = FakeRunner()

    status = manage_hydrolix_stack.deploy_stack(
        runner,
        assume_yes=True,
        environ={"AWS_REGION": "us-west-2"},
        ask=lambda _: "y",
    )

    assert status == 1
    assert runner.calls == []
    assert "AGENT_MODEL_ID, HYDROLIX_TABLE" in capsys.readouterr().out


def test_declined_deploy_does_not_clone_install_or_deploy():
    runner = FakeRunner()

    status = manage_hydrolix_stack.deploy_stack(
        runner,
        assume_yes=False,
        environ=SETTINGS,
        ask=lambda _: "n",
    )

    assert status == 1
    assert runner.matching("git clone") == []
    assert runner.matching("npm ci") == []
    assert runner.matching("cdk deploy") == []


def test_deploy_stops_when_the_pinned_checkout_fails(monkeypatch, tmp_path):
    isolate_paths(monkeypatch, tmp_path)
    runner = FakeRunner(failing=("git checkout",))

    status = manage_hydrolix_stack.deploy_stack(
        runner,
        assume_yes=True,
        environ=SETTINGS,
        ask=lambda _: "y",
    )

    assert status == 9
    assert runner.matching("npm ci") == []
    assert runner.matching("cdk deploy") == []


def test_destroy_lists_and_deletes_configured_amplify_app(monkeypatch, tmp_path, capsys):
    destination = isolate_paths(monkeypatch, tmp_path)
    destination.mkdir(parents=True)
    runner = FakeRunner()
    environ = {**SETTINGS, "HYDROLIX_AMPLIFY_APP_ID": "demo-app"}

    status = manage_hydrolix_stack.destroy_stack(
        runner,
        assume_yes=False,
        environ=environ,
        ask=lambda _: "y",
    )

    assert status == 0
    [delete_app] = runner.matching("amplify delete-app")
    assert delete_app[-1] == "demo-app"
    [destroy] = runner.matching("cdk destroy")
    assert destroy[-1] == "--force"
    assert not destination.exists()
    output = capsys.readouterr().out
    assert "demo-app" in output
    assert "stack-generated Hydrolix credentials (deleted)" in output


def test_destroy_without_an_amplify_id_names_the_manual_cleanup(monkeypatch, tmp_path, capsys):
    isolate_paths(monkeypatch, tmp_path)
    runner = FakeRunner()

    status = manage_hydrolix_stack.destroy_stack(
        runner,
        assume_yes=True,
        environ=SETTINGS,
        ask=lambda _: "n",
    )

    assert status == 0
    assert runner.matching("amplify delete-app") == []
    output = capsys.readouterr().out
    assert "set HYDROLIX_AMPLIFY_APP_ID if created" in output
    assert "No Amplify app was deleted" in output


def test_failed_amplify_delete_stops_before_cdk_destroy(monkeypatch, tmp_path):
    isolate_paths(monkeypatch, tmp_path)
    runner = FakeRunner(failing=("amplify delete-app",))

    status = manage_hydrolix_stack.destroy_stack(
        runner,
        assume_yes=True,
        environ={**SETTINGS, "HYDROLIX_AMPLIFY_APP_ID": "demo-app"},
        ask=lambda _: "y",
    )

    assert status == 9
    assert runner.matching("cdk destroy") == []


def test_missing_amplify_app_does_not_stop_backend_teardown(monkeypatch, tmp_path, capsys):
    isolate_paths(monkeypatch, tmp_path)
    runner = FakeRunner(missing=("amplify delete-app",))

    status = manage_hydrolix_stack.destroy_stack(
        runner,
        assume_yes=True,
        environ={**SETTINGS, "HYDROLIX_AMPLIFY_APP_ID": "already-gone"},
        ask=lambda _: "n",
    )

    assert status == 0
    assert runner.matching("cdk destroy")
    assert "already absent; continuing teardown" in capsys.readouterr().out


def test_destroy_mentions_the_remaining_cdk_asset_image(monkeypatch, tmp_path, capsys):
    isolate_paths(monkeypatch, tmp_path)

    status = manage_hydrolix_stack.destroy_stack(
        FakeRunner(),
        assume_yes=True,
        environ=SETTINGS,
        ask=lambda _: "n",
    )

    assert status == 0
    assert "ECR repository may retain" in capsys.readouterr().out


@pytest.mark.parametrize("command", ["deploy", "destroy"])
def test_unknown_flags_are_rejected(command):
    with pytest.raises(SystemExit):
        manage_hydrolix_stack.main([command, "--force"], runner=FakeRunner())
