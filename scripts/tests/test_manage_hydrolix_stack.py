import importlib.util
import json
import re
import subprocess
from pathlib import Path

import manage_hydrolix_stack
import pytest
from pydantic import ValidationError

SETTINGS = {
    "AWS_REGION": "us-west-2",
    "AGENT_MODEL_ID": "us.anthropic.claude-sonnet-4-6",
    "HYDROLIX_TABLE": "video.cmcd",
}


class FakeRunner:
    def __init__(
        self,
        *,
        account="111122223333",
        failing=(),
        missing=(),
        stack_exists=True,
        secret_arn=None,
        amplify_app_name="Hydrolix dashboard",
    ):
        self.account = account
        self.bootstrap = (0, '{"status": "UPDATE_COMPLETE", "qualifier": "hnb659fds"}', "")
        self.bootstrap_version = (0, "21\n", "")
        # What `cdk diff --security-only` prints (to stderr) when nothing security-related changes
        self.security_diff = (
            0, "", f"Stack {manage_hydrolix_stack.STACK}\nThere were no security-related changes\n"
        )  # fmt: skip
        self.retired_table = None
        self.failing = failing
        self.missing = missing
        self.stack_exists = stack_exists
        self.amplify_app_name = amplify_app_name
        self.secret_arn = (
            secret_arn or "arn:aws:secretsmanager:us-west-2:111122223333:secret:hydrolix"
        )
        self.calls = []

    def __call__(self, arguments, cwd, capture):
        call = (list(arguments), cwd, capture)
        self.calls.append(call)
        joined = " ".join(arguments)
        if any(fragment in joined for fragment in self.failing):
            return subprocess.CompletedProcess(arguments, 9, "", "failed")
        if any(fragment in joined for fragment in self.missing):
            operation = "GetApp" if "get-app" in joined else "DeleteApp"
            message = (
                f"An error occurred (NotFoundException) when calling the {operation} operation"
            )
            return subprocess.CompletedProcess(arguments, 254, "", message)
        if "--stack-name CDKToolkit" in joined:
            return subprocess.CompletedProcess(arguments, *self.bootstrap)
        if "/cdk-bootstrap/" in joined:
            return subprocess.CompletedProcess(arguments, *self.bootstrap_version)
        if "--security-only" in joined:
            return subprocess.CompletedProcess(arguments, *self.security_diff)
        if "get-caller-identity" in joined:
            status = 0 if self.account else 1
            return subprocess.CompletedProcess(arguments, status, f"{self.account or ''}\n", "")
        if "cloudformation describe-stacks" in joined:
            if not self.stack_exists:
                message = (
                    "An error occurred (ValidationError) when calling DescribeStacks: "
                    f"Stack with id {manage_hydrolix_stack.STACK} does not exist"
                )
                return subprocess.CompletedProcess(arguments, 255, "", message)
            outputs = [{"OutputKey": "HydrolixSecretArn", "OutputValue": self.secret_arn}]
            if self.retired_table:
                retired = {"OutputKey": "RetiredQueryResultsTableName"}
                outputs.append(retired | {"OutputValue": self.retired_table})
            stack = {"StackStatus": "CREATE_COMPLETE", "Outputs": outputs}
            return subprocess.CompletedProcess(arguments, 0, json.dumps({"Stacks": [stack]}), "")
        if "amplify get-app" in joined:
            app_id = arguments[arguments.index("--app-id") + 1]
            app = {"app": {"appId": app_id, "name": self.amplify_app_name}}
            return subprocess.CompletedProcess(arguments, 0, json.dumps(app), "")
        if arguments[:2] == ["git", "clone"]:
            checkout = Path(arguments[-1])
            package = checkout / "mcp_hydrolix"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text("")
            (checkout / "LICENSE").write_text("Apache License 2.0")
            (checkout / "NOTICE").write_text("mcp-hydrolix notice")
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


def load_hydrolix_runtime_settings_module():
    path = manage_hydrolix_stack.AGENT_DIRECTORY / "src" / "settings" / "runtime_settings.py"
    spec = importlib.util.spec_from_file_location("hydrolix_runtime_settings", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("missing", ["AGENT_MODEL_ID", "MEMORY_ID"])
def test_the_runtime_refuses_to_start_without_its_model_or_memory(missing, monkeypatch):
    settings = load_hydrolix_runtime_settings_module()
    monkeypatch.setenv("AGENT_MODEL_ID", "us.anthropic.claude-sonnet-4-6")
    monkeypatch.setenv("MEMORY_ID", "example-memory")
    monkeypatch.delenv(missing)

    with pytest.raises(ValidationError, match=f"Missing required setting\\(s\\): {missing}"):
        settings.RuntimeSettings()


def test_the_cdk_stack_sets_the_memory_id_the_runtime_requires():
    stack = (
        manage_hydrolix_stack.CDK_DIRECTORY
        / "cdklib"
        / "cdk-hydrolix-data-assistant-agentcore-strands-stack.ts"
    ).read_text()
    assert "MEMORY_ID: agentMemory.attrMemoryId" in stack


def test_docker_requirement_cannot_be_parsed_as_a_shell_redirect():
    dockerfile = (manage_hydrolix_stack.AGENT_DIRECTORY / "Dockerfile").read_text()

    assert 'uv pip install "aws-opentelemetry-distro>=0.10.1"' in dockerfile
    assert "uv pip install aws-opentelemetry-distro>=" not in dockerfile


def test_mcp_pin_is_a_full_commit_sha_named_by_its_release_tag():
    # Offline shape check only; the CI docker-build proves the commit exists upstream.
    script = Path(manage_hydrolix_stack.__file__).read_text()
    pin = re.search(r'^MCP_COMMIT = "([0-9a-f]{40})"  # (v\d+\.\d+\.\d+)$', script, re.M)

    assert pin, "MCP_COMMIT must be a full 40-hex SHA followed by '# vX.Y.Z'"
    assert pin.group(1) == manage_hydrolix_stack.MCP_COMMIT
    requirements = (manage_hydrolix_stack.AGENT_DIRECTORY / "requirements.txt").read_text()
    assert f"mcp_hydrolix {pin.group(2)}," in requirements
    assert f"constraint-dependencies (mcp_hydrolix {pin.group(2)})" in requirements


MCP_TOOL_INPUTS = Path(__file__).parent / "fixtures" / "mcp_hydrolix_tool_inputs.json"
PROMPTS = ("hydrolix_agent", "cache_origin", "qoe_analysis")


def read_documented_inputs(prompt: str) -> dict[str, dict[str, dict[str, object]]]:
    """Read each "* `tool`" heading and its "* Input: `name` (type, required)" lines."""
    tools: dict[str, dict[str, dict[str, object]]] = {}
    current = None
    for line in prompt.splitlines():
        if heading := re.match(r"^\* `(\w+)`$", line):
            current = tools.setdefault(heading.group(1), {})
        elif (field := re.match(r"^  \* Input: `(\w+)` \((\w+), (required|optional)\)", line)) and (
            current is not None
        ):
            current[field.group(1)] = {
                "type": field.group(2),
                "required": field.group(3) == "required",
            }
    return tools


@pytest.mark.parametrize("prompt", PROMPTS)
def test_prompts_document_the_pinned_mcp_tool_inputs_exactly(prompt):
    """Each Hydrolix tool a prompt documents has the pinned release's inputs. Which tools the
    subagents get is test_hydrolix_bound_model_sql's: not list_databases or list_tables.
    """
    recorded = json.loads(MCP_TOOL_INPUTS.read_text())
    assert recorded["commit"] == manage_hydrolix_stack.MCP_COMMIT
    text = (
        manage_hydrolix_stack.AGENT_DIRECTORY / "src" / "tools" / f"{prompt}_instructions.txt"
    ).read_text()
    documented = read_documented_inputs(text)
    hydrolix_tools = set(documented) & set(recorded["tools"])

    assert hydrolix_tools == {"run_select_query", "get_table_info"}, prompt
    for tool in hydrolix_tools:
        assert documented[tool] == recorded["tools"][tool], (
            f"{prompt}: {tool} inputs differ from {recorded['release']}"
        )


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
    assert "agentModelId=us.anthropic.claude-sonnet-4-6" in deploy
    assert not any(argument.startswith("BedrockModelId=") for argument in deploy)
    assert "HydrolixTable=video.cmcd" in deploy
    assert deploy[deploy.index("--require-approval") + 1] == "never"
    assert runner.matching("npm ci")
    assert (destination / "__init__.py").exists()
    assert (destination / "LICENSE").read_text() == "Apache License 2.0"
    assert (destination / "NOTICE").read_text() == "mcp-hydrolix notice"


def test_deploy_refuses_to_redistribute_mcp_source_without_its_license(
    monkeypatch, tmp_path, capsys
):
    isolate_paths(monkeypatch, tmp_path)

    def runner(arguments, cwd, capture):
        if arguments[:2] == ["git", "clone"]:
            package = Path(arguments[-1]) / "mcp_hydrolix"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text("")
        return subprocess.CompletedProcess(arguments, 0, "", "")

    status = manage_hydrolix_stack.install_pinned_mcp_server(runner)

    assert status == 1
    assert "does not contain LICENSE" in capsys.readouterr().out


JWT_SETTINGS = {
    "HYDROLIX_JWT_DISCOVERY_URL": (
        "https://cognito-idp.us-west-2.amazonaws.com/us-west-2_EXAMPLE"
        "/.well-known/openid-configuration"
    ),
    "HYDROLIX_JWT_CLIENT_IDS": "example-app-client",
}


def test_deploy_passes_jwt_auth_and_names_the_caller_model(monkeypatch, tmp_path, capsys):
    isolate_paths(monkeypatch, tmp_path)
    runner = FakeRunner()

    status = manage_hydrolix_stack.deploy_stack(
        runner, assume_yes=False, environ=SETTINGS | JWT_SETTINGS, ask=lambda _: "y"
    )

    assert status == 0
    [deploy] = runner.matching("cdk deploy")
    assert f"jwtDiscoveryUrl={JWT_SETTINGS['HYDROLIX_JWT_DISCOVERY_URL']}" in deploy
    assert "jwtClientIds=example-app-client" in deploy
    assert "actor = token sub" in capsys.readouterr().out


def test_deploy_without_jwt_says_memory_is_off(monkeypatch, tmp_path, capsys):
    isolate_paths(monkeypatch, tmp_path)
    runner = FakeRunner()

    manage_hydrolix_stack.deploy_stack(
        runner, assume_yes=False, environ=SETTINGS, ask=lambda _: "y"
    )

    [deploy] = runner.matching("cdk deploy")
    assert not any(argument.startswith("jwt") for argument in deploy)
    assert "memory off" in capsys.readouterr().out


@pytest.mark.parametrize("name", sorted(JWT_SETTINGS))
def test_half_a_jwt_setting_stops_before_any_aws_call(name, capsys):
    runner = FakeRunner()

    status = manage_hydrolix_stack.deploy_stack(
        runner, assume_yes=True, environ=SETTINGS | {name: JWT_SETTINGS[name]}, ask=lambda _: "y"
    )

    assert status == 1
    assert runner.calls == []
    assert "HYDROLIX_JWT_DISCOVERY_URL" in capsys.readouterr().out


def test_an_interactive_deploy_confirms_once_and_cdk_never_asks_again(monkeypatch, tmp_path):
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
    assert deploy[deploy.index("--require-approval") + 1] == "never"


# --- One confirmation, before anything is fetched or built -------------------------------


def test_the_security_diff_comes_before_the_prompt_and_the_mcp_checkout_after(
    monkeypatch, tmp_path
):
    isolate_paths(monkeypatch, tmp_path)
    runner, before_prompt = FakeRunner(), []

    def ask(_):
        before_prompt.extend(" ".join(call[0]) for call in runner.calls)
        return "y"

    status = manage_hydrolix_stack.deploy_stack(runner, assume_yes=False, environ=SETTINGS, ask=ask)

    assert status == 0
    [diff] = [call for call in before_prompt if " diff " in call]
    assert "--security-only" in diff and "--method template" in diff
    assert not any("git clone" in call or " deploy " in call for call in before_prompt)
    assert runner.matching("git clone") and runner.matching("cdk deploy")


def test_without_a_terminal_it_stops_at_the_prompt_before_fetching_or_building(
    monkeypatch, tmp_path, capsys
):
    isolate_paths(monkeypatch, tmp_path)
    runner = FakeRunner()

    status = manage_hydrolix_stack.deploy_stack(
        runner, assume_yes=False, environ=SETTINGS, ask=lambda _: "y", interactive=False
    )

    assert status == 1
    assert runner.matching("git clone") == [] and runner.matching("cdk deploy") == []
    assert "no terminal: re-run with --yes" in capsys.readouterr().out.lower()


def test_yes_says_that_cdk_will_not_ask_and_deploys(monkeypatch, tmp_path, capsys):
    isolate_paths(monkeypatch, tmp_path)
    runner = FakeRunner()

    status = manage_hydrolix_stack.deploy_stack(
        runner, assume_yes=True, environ=SETTINGS, ask=lambda _: "n", interactive=False
    )

    assert status == 0
    output = capsys.readouterr().out
    assert "--yes (no prompt): CDK deploys with --require-approval never" in output
    assert "CDK bootstrap: found (CDKToolkit, qualifier hnb659fds, version 21)" in output


def test_a_missing_bootstrap_stops_before_anything_is_fetched(monkeypatch, tmp_path, capsys):
    isolate_paths(monkeypatch, tmp_path)
    runner = FakeRunner()
    runner.bootstrap = (
        254, "", "An error occurred (ValidationError) when calling DescribeStacks: "
        "Stack with id CDKToolkit does not exist",
    )  # fmt: skip

    status = manage_hydrolix_stack.deploy_stack(
        runner, assume_yes=True, environ=SETTINGS, ask=lambda _: "y"
    )

    assert status == 1
    assert runner.matching("npm ci") == [] and runner.matching("git clone") == []
    assert "CDK bootstrap: missing in aws://111122223333/us-west-2" in capsys.readouterr().out


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
    # Only the plan ran (npm ci for the CDK CLI, a template-only diff): nothing fetched or built.
    assert runner.matching("git clone") == []
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
    assert "Hydrolix dashboard (demo-app)" in output
    assert "demo-app" in output
    assert runner.secret_arn in output


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
    assert "Amplify app: none found" in output
    assert "No Amplify app was deleted" in output


def test_failed_amplify_delete_still_attempts_cdk_destroy(monkeypatch, tmp_path, capsys):
    isolate_paths(monkeypatch, tmp_path)
    runner = FakeRunner(failing=("amplify delete-app",))

    status = manage_hydrolix_stack.destroy_stack(
        runner,
        assume_yes=True,
        environ={**SETTINGS, "HYDROLIX_AMPLIFY_APP_ID": "demo-app"},
        ask=lambda _: "y",
    )

    assert status == 1
    assert runner.matching("cdk destroy")
    assert "Amplify app: Hydrolix dashboard (demo-app)" in capsys.readouterr().out


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
    assert len(runner.matching("amplify delete-app")) == 1
    assert "already absent; continuing teardown" in capsys.readouterr().out


def test_missing_stack_and_app_return_without_prompt_or_cleanup(capsys):
    runner = FakeRunner(stack_exists=False, missing=("amplify get-app",))
    asked = []

    status = manage_hydrolix_stack.destroy_stack(
        runner,
        assume_yes=False,
        environ={**SETTINGS, "HYDROLIX_AMPLIFY_APP_ID": "already-gone"},
        ask=lambda prompt: asked.append(prompt) or "y",
    )

    assert status == 0
    assert asked == []
    assert len(runner.matching("amplify get-app")) == 1
    assert runner.matching("amplify delete-app") == []
    assert runner.matching("npm ci") == []
    assert runner.matching("cdk destroy") == []
    assert "already absent" in capsys.readouterr().out


def test_incomplete_amplify_details_stop_before_prompt_or_cleanup(capsys):
    runner = FakeRunner(amplify_app_name="")
    asked = []

    status = manage_hydrolix_stack.destroy_stack(
        runner,
        assume_yes=False,
        environ={**SETTINGS, "HYDROLIX_AMPLIFY_APP_ID": "configured-app"},
        ask=lambda prompt: asked.append(prompt) or "y",
    )

    assert status == 1
    assert asked == []
    assert runner.matching("amplify delete-app") == []
    assert runner.matching("cdk destroy") == []
    assert "incomplete details" in capsys.readouterr().out


def test_app_only_rerun_deletes_the_remaining_amplify_app_without_cdk(capsys):
    runner = FakeRunner(stack_exists=False)
    asked = []

    status = manage_hydrolix_stack.destroy_stack(
        runner,
        assume_yes=False,
        environ={**SETTINGS, "HYDROLIX_AMPLIFY_APP_ID": "remaining-app"},
        ask=lambda prompt: asked.append(prompt) or "y",
    )

    assert status == 0
    assert len(asked) == 1
    assert len(runner.matching("amplify delete-app")) == 1
    assert runner.matching("npm ci") == []
    assert runner.matching("cdk destroy") == []
    output = capsys.readouterr().out
    assert "CloudFormation stack: already absent" in output
    assert "Amplify app: Hydrolix dashboard (remaining-app)" in output
    assert "Teardown complete" in output


def test_failed_app_only_rerun_reports_the_remaining_app_without_cdk(capsys):
    runner = FakeRunner(stack_exists=False, failing=("amplify delete-app",))

    status = manage_hydrolix_stack.destroy_stack(
        runner,
        assume_yes=True,
        environ={**SETTINGS, "HYDROLIX_AMPLIFY_APP_ID": "remaining-app"},
        ask=lambda _: "n",
    )

    assert status == 1
    assert len(runner.matching("amplify delete-app")) == 1
    assert runner.matching("npm ci") == []
    assert runner.matching("cdk destroy") == []
    output = capsys.readouterr().out
    assert "Remaining resources:" in output
    assert "- Amplify app: Hydrolix dashboard (remaining-app)" in output
    assert "CloudFormation stack:" not in output.split("Remaining resources:", 1)[1]


def test_failed_stack_lookup_returns_without_prompt_or_cleanup(capsys):
    runner = FakeRunner(failing=("cloudformation describe-stacks",))
    asked = []

    status = manage_hydrolix_stack.destroy_stack(
        runner,
        assume_yes=False,
        environ=SETTINGS,
        ask=lambda prompt: asked.append(prompt) or "y",
    )

    assert status == 1
    assert asked == []
    assert runner.matching("cdk destroy") == []
    assert "Nothing was deleted" in capsys.readouterr().out


def test_failed_cdk_destroy_reports_the_stack_and_secret(monkeypatch, tmp_path, capsys):
    isolate_paths(monkeypatch, tmp_path)
    runner = FakeRunner(failing=("cdk destroy",))

    status = manage_hydrolix_stack.destroy_stack(
        runner,
        assume_yes=True,
        environ=SETTINGS,
        ask=lambda _: "y",
    )

    assert status == 1
    output = capsys.readouterr().out
    assert f"CloudFormation stack: {manage_hydrolix_stack.STACK}" in output
    assert f"Secrets Manager secret: {runner.secret_arn}" in output
    assert "Amplify app:" not in output.split("Teardown incomplete.", 1)[1]


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


@pytest.mark.parametrize(
    "half",
    [
        {"HYDROLIX_JWT_ISSUER": "https://cognito-idp.us-west-2.amazonaws.com/us-west-2_EXAMPLE"},
        {"HYDROLIX_JWT_ALLOWED_CLIENTS": "example-app-client"},
    ],
    ids=["issuer-only", "clients-only"],
)
def test_the_runtime_refuses_half_a_jwt_setting(half, monkeypatch):
    settings = load_hydrolix_runtime_settings_module()
    monkeypatch.setenv("AGENT_MODEL_ID", "us.anthropic.claude-sonnet-4-6")
    monkeypatch.setenv("MEMORY_ID", "example-memory")
    monkeypatch.setenv("HYDROLIX_TABLE", "video.cmcd")
    for name in ("HYDROLIX_JWT_ISSUER", "HYDROLIX_JWT_ALLOWED_CLIENTS"):
        monkeypatch.delenv(name, raising=False)
    for name, value in half.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError, match="or neither"):
        settings.RuntimeSettings()


def test_an_empty_security_diff_fetches_and_deploys_nothing(monkeypatch, tmp_path, capsys):
    isolate_paths(monkeypatch, tmp_path)
    runner = FakeRunner()
    runner.security_diff = (0, "", "")

    status = manage_hydrolix_stack.deploy_stack(
        runner, assume_yes=True, environ=SETTINGS, ask=lambda _: "y"
    )

    assert status == 1
    assert runner.matching("git clone") == [] and runner.matching(" deploy ") == []
    assert "printed nothing" in capsys.readouterr().out


def test_a_bootstrap_with_another_qualifier_stops_before_the_checkout(monkeypatch, tmp_path):
    isolate_paths(monkeypatch, tmp_path)
    runner = FakeRunner()
    runner.bootstrap = (0, '{"status": "UPDATE_COMPLETE", "qualifier": "custom1"}', "")

    status = manage_hydrolix_stack.deploy_stack(
        runner, assume_yes=True, environ=SETTINGS, ask=lambda _: "y"
    )

    assert status == 1
    assert runner.matching("npm ci") == [] and runner.matching("git clone") == []


def test_destroy_leaves_the_earlier_results_table_and_only_prints_how_to_delete_it(
    monkeypatch, tmp_path, capsys
):
    isolate_paths(monkeypatch, tmp_path)
    runner = FakeRunner()
    runner.retired_table = (
        "CdkHydrolixDataAssistantAgentcoreStrandsStack-RawQueryResults82B00746-EXAMPLE"
    )

    status = manage_hydrolix_stack.destroy_stack(
        runner, assume_yes=False, environ=SETTINGS, ask=lambda _: "y"
    )

    assert status == 0
    output = capsys.readouterr().out
    assert f"{runner.retired_table} (left in place by design)" in output
    assert (
        f"aws dynamodb delete-table --region us-west-2 --table-name {runner.retired_table}"
        in output
    )
    assert runner.matching("delete-table") == []  # printed for the operator, never run


def test_the_security_diff_and_the_deploy_get_the_same_model(monkeypatch, tmp_path):
    """The model reaches both syntheses as context (cdk diff takes no --parameters),
    and the deploy uses the template default it sets, never a previous stack value."""
    isolate_paths(monkeypatch, tmp_path)
    runner = FakeRunner()
    eu_model = ".".join(["eu", "anthropic.claude-sonnet-4-6"])

    status = manage_hydrolix_stack.deploy_stack(
        runner, assume_yes=True, environ=SETTINGS | {"AGENT_MODEL_ID": eu_model}, ask=lambda _: "y"
    )

    assert status == 0
    [diff] = runner.matching("--security-only")
    [deploy] = [call for call in runner.matching(" deploy ") if "--require-approval" in call]

    def model_inputs(call):
        return [a for a in call if "agentModelId=" in a or "BedrockModelId" in a]

    assert model_inputs(diff) == model_inputs(deploy) == [f"agentModelId={eu_model}"]
    assert "--no-previous-parameters" in deploy


def test_the_plan_names_the_model_the_deploy_grants(monkeypatch, tmp_path, capsys):
    isolate_paths(monkeypatch, tmp_path)
    manage_hydrolix_stack.deploy_stack(
        FakeRunner(), assume_yes=True, environ=SETTINGS, ask=lambda _: "y"
    )
    assert "Bedrock model granted: us.anthropic.claude-sonnet-4-6" in capsys.readouterr().out
