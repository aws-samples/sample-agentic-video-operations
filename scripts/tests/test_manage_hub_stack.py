"""`just deploy|destroy hub`: confirmed, settings from .env, fail-closed, exact leftovers."""

import subprocess

import manage_hub_stack as hub
import pytest

ENV = {"AWS_REGION": "us-west-2", "AGENT_MODEL_ID": "us.anthropic.claude-sonnet-4-6"}
DENIED = "An error occurred (AccessDeniedException) when calling X: arn:aws:sts::111122223333:role/NotFound"  # noqa: E501
NO_STACK = "An error occurred (ValidationError) when calling DescribeStacks: Stack with id MediaOpsHubStack does not exist"  # noqa: E501


class FakeRunner:
    """Answers by the first matching argument fragment; records every call."""

    def __init__(self, answers=None):
        self.answers = {"get-caller-identity": (0, "111122223333", "")} | (answers or {})
        self.calls = []

    def __call__(self, arguments, cwd, capture):
        self.calls.append(list(arguments))
        joined = " ".join(arguments)
        for fragment, (code, out, err) in self.answers.items():
            if fragment in joined:
                return subprocess.CompletedProcess(arguments, code, out, err)
        return subprocess.CompletedProcess(arguments, 0, "", "")

    def ran(self, fragment):
        return [call for call in self.calls if fragment in " ".join(call)]


def test_deploy_passes_domains_writes_and_models_from_the_env_to_cdk():
    runner = FakeRunner()
    env = ENV | {"MEDIA_DOMAINS": "medialive,mediaconnect", "ALLOW_WRITES": "true",
                 "THUMBNAIL_MODEL_ID": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
                 "HUB_WRITE_TAG": "MediaOpsManaged=true"}  # fmt: skip

    assert hub.main(["deploy", "--yes"], runner, environ=env) == 0

    [deploy] = runner.ran(" deploy MediaOpsHubStack")
    assert "mediaDomains=medialive,mediaconnect" in deploy
    assert "allowWrites=true" in deploy
    assert "writeTag=MediaOpsManaged=true" in deploy
    assert "BedrockModelId=us.anthropic.claude-sonnet-4-6" in deploy
    assert "ThumbnailModelId=us.anthropic.claude-haiku-4-5-20251001-v1:0" in deploy
    assert deploy[deploy.index("--require-approval") + 1] == "never"


def test_deploy_defaults_to_both_packs_without_writes_and_asks_for_iam_broadening():
    runner = FakeRunner()

    assert hub.main(["deploy"], runner, ask=lambda _: "y", environ=ENV) == 0

    [deploy] = runner.ran(" deploy MediaOpsHubStack")
    assert "mediaDomains=medialive,mediaconnect" in deploy
    assert "allowWrites=false" in deploy
    assert not any(argument.startswith("writeTag=") for argument in deploy)
    assert deploy[deploy.index("--require-approval") + 1] == "broadening"


def test_invalid_write_tag_stops_before_any_aws_call(capsys):
    runner = FakeRunner()

    assert (
        hub.main(
            ["deploy", "--yes"],
            runner,
            environ=ENV | {"ALLOW_WRITES": "true", "HUB_WRITE_TAG": "bad key=value"},
        )
        == 1
    )

    assert runner.calls == []
    assert "HUB_WRITE_TAG must be Key=Value" in capsys.readouterr().out


def test_deploy_confirmation_names_account_wide_or_tagged_write_scope(capsys):
    runner = FakeRunner()
    hub.main(
        ["deploy"],
        runner,
        ask=lambda _: "n",
        environ=ENV | {"ALLOW_WRITES": "true"},
    )
    assert "all selected-pack resources in this account and region" in capsys.readouterr().out

    runner = FakeRunner()
    hub.main(
        ["deploy"],
        runner,
        ask=lambda _: "n",
        environ=ENV | {"ALLOW_WRITES": "true", "HUB_WRITE_TAG": "MediaOpsManaged=true"},
    )
    assert "resources tagged MediaOpsManaged=true" in capsys.readouterr().out


def test_deploy_without_a_model_stops_before_any_aws_call(capsys):
    runner = FakeRunner()

    assert hub.main(["deploy", "--yes"], runner, environ={"AWS_REGION": "us-west-2"}) == 1

    assert runner.calls == []
    assert "AGENT_MODEL_ID" in capsys.readouterr().out


def test_declined_deploy_runs_nothing():
    runner = FakeRunner()

    assert hub.main(["deploy"], runner, ask=lambda _: "n", environ=ENV) == 1

    assert runner.ran("npm") == [] and runner.ran(" deploy ") == []


def test_destroy_deletes_the_stack_then_the_runtime_log_groups():
    groups = f"{hub.RUNTIME_LOG_PREFIX}abc-DEFAULT {hub.RUNTIME_LOG_PREFIX}abc-otel"
    runner = FakeRunner({"describe-log-groups": (0, groups, "")})

    assert hub.main(["destroy", "--yes"], runner, environ=ENV) == 0

    order = [i for i, c in enumerate(runner.calls) if "destroy" in c or "delete-log-group" in c]
    assert [runner.calls[i][1] if "destroy" in runner.calls[i] else "logs" for i in order] == [
        "destroy", "logs", "logs",
    ]  # fmt: skip


def test_destroy_of_an_absent_hub_deletes_nothing(capsys):
    runner = FakeRunner(
        {"describe-stacks": (254, "", NO_STACK), "describe-log-groups": (0, "", "")}
    )  # noqa: E501

    assert hub.main(["destroy", "--yes"], runner, environ=ENV) == 0

    assert runner.ran(" destroy ") == [] and runner.ran("delete-log-group") == []
    assert "already absent" in capsys.readouterr().out


def test_a_denied_stack_lookup_is_not_mistaken_for_an_absent_stack(capsys):
    runner = FakeRunner({"describe-stacks": (254, "", DENIED)})

    assert hub.main(["destroy", "--yes"], runner, environ=ENV) == 1

    assert runner.ran(" destroy ") == [] and runner.ran("delete-log-group") == []
    assert "Nothing was deleted" in capsys.readouterr().out


def test_a_second_run_after_the_stack_is_gone_cleans_the_remaining_log_groups():
    group = f"{hub.RUNTIME_LOG_PREFIX}abc-DEFAULT"
    runner = FakeRunner(
        {"describe-stacks": (254, "", NO_STACK), "describe-log-groups": (0, group, "")}
    )  # noqa: E501

    assert hub.main(["destroy", "--yes"], runner, environ=ENV) == 0

    assert runner.ran(" destroy ") == []
    assert len(runner.ran("delete-log-group")) == 1


def test_a_failed_stack_destroy_still_cleans_logs_and_lists_exactly_what_remains(capsys):
    group = f"{hub.RUNTIME_LOG_PREFIX}abc-DEFAULT"
    runner = FakeRunner(
        {"describe-log-groups": (0, group, ""), "destroy MediaOpsHubStack": (1, "", "")}
    )  # noqa: E501

    assert hub.main(["destroy", "--yes"], runner, environ=ENV) == 1

    out = capsys.readouterr().out
    assert "- CloudFormation stack MediaOpsHubStack" in out
    assert group not in out.split("Remaining resources:")[1]
    assert len(runner.ran("delete-log-group")) == 1


@pytest.mark.parametrize("command", ["deploy", "destroy"])
def test_without_credentials_nothing_is_asked_or_run(command, capsys):
    runner = FakeRunner({"get-caller-identity": (255, "", "Unable to locate credentials")})

    assert hub.main([command], runner, ask=lambda _: pytest.fail("asked"), environ=ENV) == 1

    assert len(runner.calls) == 1


def test_destroy_deletes_only_this_runtimes_log_groups_not_similarly_named_ones():
    owned = f"{hub.RUNTIME_LOG_PREFIX}AbCdEf1234-DEFAULT"
    runner = FakeRunner({"describe-log-groups": (0, owned, "")})

    assert hub.main(["destroy", "--yes"], runner, environ=ENV) == 0

    [lookup] = runner.ran("describe-log-groups")
    assert lookup[lookup.index("--log-group-name-prefix") + 1] == (
        "/aws/bedrock-agentcore/runtimes/MediaOpsHubRuntime-"
    )
    deleted = [c[c.index("--log-group-name") + 1] for c in runner.ran("delete-log-group")]
    assert deleted == [owned]


def test_the_log_prefix_cannot_match_a_similarly_named_runtime():
    foreign = "/aws/bedrock-agentcore/runtimes/MediaOpsHubRuntime2-AbCdEf1234-DEFAULT"
    assert not foreign.startswith(hub.RUNTIME_LOG_PREFIX)


def test_the_runtime_name_matches_the_cdk_stack():
    stack = (hub.CDK_DIRECTORY / "lib" / "media-ops-hub-stack.ts").read_text()
    assert f"export const RUNTIME_NAME = '{hub.RUNTIME_NAME}';" in stack


def test_deploy_attaches_the_invoke_policy_to_the_named_role_only_when_set():
    runner = FakeRunner()
    hub.main(
        ["deploy", "--yes"], runner, environ=ENV | {"HUB_INVOKER_ROLE_NAME": "media-ops-operator"}
    )  # noqa: E501
    [deploy] = runner.ran(" deploy MediaOpsHubStack")
    assert "invokerRoleName=media-ops-operator" in deploy

    runner = FakeRunner()
    hub.main(["deploy", "--yes"], runner, environ=ENV)
    [deploy] = runner.ran(" deploy MediaOpsHubStack")
    assert not any(argument.startswith("invokerRoleName=") for argument in deploy)


JWT_ENV = {
    "HUB_JWT_DISCOVERY_URL": "https://cognito-idp.us-west-2.amazonaws.com/us-west-2_EXAMPLE/.well-known/openid-configuration",
    "HUB_JWT_CLIENT_IDS": "example-client-id",
}  # fmt: skip


def test_deploy_passes_jwt_auth_to_cdk_and_names_it_in_the_confirmation(capsys):
    runner = FakeRunner()

    assert hub.main(["deploy"], runner, ask=lambda _: "y", environ=ENV | JWT_ENV) == 0

    [deploy] = runner.ran(" deploy MediaOpsHubStack")
    assert f"jwtDiscoveryUrl={JWT_ENV['HUB_JWT_DISCOVERY_URL']}" in deploy
    assert "jwtClientIds=example-client-id" in deploy
    assert "actor = token sub" in capsys.readouterr().out


@pytest.mark.parametrize(
    "extra",
    [
        {"HUB_JWT_DISCOVERY_URL": JWT_ENV["HUB_JWT_DISCOVERY_URL"]},
        {"HUB_JWT_CLIENT_IDS": "example-client-id"},
        JWT_ENV | {"HUB_INVOKER_ROLE_NAME": "media-ops-operator"},
    ],
    ids=["url-only", "clients-only", "jwt-and-iam-invoker"],
)
def test_incomplete_or_conflicting_auth_settings_stop_before_any_aws_call(extra, capsys):
    runner = FakeRunner()

    assert hub.main(["deploy", "--yes"], runner, environ=ENV | extra) == 1

    assert runner.calls == []
    assert "HUB_JWT" in capsys.readouterr().out
