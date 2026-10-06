"""`just deploy|destroy agentic-iops-streaming`: confirmed, settings from .env, fail-closed, exact
leftovers."""

import subprocess

import manage_agentic_iops_streaming_stack as stack_script
import pytest

ENV = {"AWS_REGION": "us-west-2", "AGENT_MODEL_ID": "us.anthropic.claude-sonnet-4-6"}
DENIED = "An error occurred (AccessDeniedException) when calling X: arn:aws:sts::111122223333:role/NotFound"  # noqa: E501
NO_STACK = "An error occurred (ValidationError) when calling DescribeStacks: Stack with id AgenticIopsStreamingStack does not exist"  # noqa: E501

BOOTSTRAPPED = (0, '{"status": "UPDATE_COMPLETE", "qualifier": "hnb659fds"}', "")
# What `cdk diff --security-only` prints (to stderr) when nothing security-related changes.
NO_SECURITY_CHANGES = (
    0,
    "",
    "Stack AgenticIopsStreamingStack\nThere were no security-related changes "
    "(limitations: https://github.com/aws/aws-cdk/issues/1299)\n",
)


class FakeRunner:
    """Answers by the first matching argument fragment; records every call."""

    def __init__(self, answers=None):
        self.answers = {
            "get-caller-identity": (0, "111122223333", ""),
            "--stack-name CDKToolkit": BOOTSTRAPPED,
            "/cdk-bootstrap/hnb659fds/version": (0, "21\n", ""),
            "--security-only": NO_SECURITY_CHANGES,
        } | (answers or {})
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
                 "AGENTIC_IOPS_WRITE_TAG": "MediaOpsManaged=true"}  # fmt: skip

    assert stack_script.main(["deploy", "--yes"], runner, environ=env) == 0

    [deploy] = runner.ran(" deploy AgenticIopsStreamingStack")
    assert "mediaDomains=medialive,mediaconnect" in deploy
    assert "allowWrites=true" in deploy
    assert "writeTag=MediaOpsManaged=true" in deploy
    assert "agentModelId=us.anthropic.claude-sonnet-4-6" in deploy
    assert "thumbnailModelId=us.anthropic.claude-haiku-4-5-20251001-v1:0" in deploy
    assert deploy[deploy.index("--require-approval") + 1] == "never"


def test_deploy_defaults_to_both_packs_without_writes_and_confirms_once():
    runner = FakeRunner()

    assert (
        stack_script.main(["deploy"], runner, ask=lambda _: "y", environ=ENV, interactive=True) == 0
    )

    [deploy] = runner.ran(" deploy AgenticIopsStreamingStack")
    assert "mediaDomains=medialive,mediaconnect" in deploy
    assert "allowWrites=false" in deploy
    assert not any(argument.startswith("writeTag=") for argument in deploy)
    # The one confirmation already showed the security diff: CDK must not ask again.
    assert deploy[deploy.index("--require-approval") + 1] == "never"


# --- T59: one confirmation, before anything is built ------------------------------------


def test_the_security_diff_is_shown_before_the_prompt_and_builds_nothing():
    runner, asked = FakeRunner(), []

    def ask(question):
        asked.append([" ".join(call) for call in runner.calls])
        return "y"

    assert stack_script.main(["deploy"], runner, ask=ask, environ=ENV, interactive=True) == 0

    [before_prompt] = asked
    [diff] = [call for call in before_prompt if " diff AgenticIopsStreamingStack" in call]
    assert "--security-only" in diff and "--method template" in diff  # no change set, no image
    assert not any(" deploy AgenticIopsStreamingStack" in call for call in before_prompt)
    assert runner.ran(" deploy AgenticIopsStreamingStack")


def test_without_a_terminal_and_without_yes_it_stops_at_the_first_prompt(capsys):
    runner = FakeRunner()

    status = stack_script.main(["deploy"], runner, environ=ENV, interactive=False)

    assert status == 1
    assert runner.ran(" deploy AgenticIopsStreamingStack") == []  # no build, no push, no stack
    output = capsys.readouterr().out
    assert "no terminal: re-run with --yes after reviewing the plan above" in output.lower()
    assert runner.ran(" diff AgenticIopsStreamingStack")  # the plan above was shown


def test_with_yes_and_no_terminal_it_deploys_without_a_second_approval():
    runner = FakeRunner()

    assert stack_script.main(["deploy", "--yes"], runner, environ=ENV, interactive=False) == 0

    [deploy] = runner.ran(" deploy AgenticIopsStreamingStack")
    assert deploy[deploy.index("--require-approval") + 1] == "never"


def test_the_bootstrap_line_comes_from_a_real_check(capsys):
    runner = FakeRunner()

    stack_script.main(["deploy", "--yes"], runner, environ=ENV)

    assert runner.ran("--stack-name CDKToolkit")
    output = capsys.readouterr().out
    assert "CDK bootstrap: found (CDKToolkit, qualifier hnb659fds, version 21)" in output
    assert "bootstrap needed" not in output.lower()


def test_a_missing_bootstrap_stops_before_anything_is_built_and_says_how(capsys):
    missing = "An error occurred (ValidationError) when calling DescribeStacks: Stack with id CDKToolkit does not exist"  # noqa: E501
    runner = FakeRunner({"--stack-name CDKToolkit": (254, "", missing)})

    assert stack_script.main(["deploy", "--yes"], runner, environ=ENV) == 1

    assert runner.ran("npm ci") == [] and runner.ran(" diff ") == []
    assert runner.ran(" deploy AgenticIopsStreamingStack") == []
    assert "CDK bootstrap: missing in aws://111122223333/us-west-2" in capsys.readouterr().out


def test_a_failed_security_diff_deploys_nothing(capsys):
    runner = FakeRunner({"--security-only": (1, "", "synth failed")})

    assert stack_script.main(["deploy", "--yes"], runner, environ=ENV) == 1

    assert runner.ran(" deploy AgenticIopsStreamingStack") == []
    assert "security diff" in capsys.readouterr().out


def test_invalid_write_tag_stops_before_any_aws_call(capsys):
    runner = FakeRunner()

    assert (
        stack_script.main(
            ["deploy", "--yes"],
            runner,
            environ=ENV | {"ALLOW_WRITES": "true", "AGENTIC_IOPS_WRITE_TAG": "bad key=value"},
        )
        == 1
    )

    assert runner.calls == []
    assert "AGENTIC_IOPS_WRITE_TAG must be Key=Value" in capsys.readouterr().out


def test_deploy_confirmation_names_account_wide_or_tagged_write_scope(capsys):
    runner = FakeRunner()
    stack_script.main(
        ["deploy"],
        runner,
        ask=lambda _: "n",
        environ=ENV | {"ALLOW_WRITES": "true"},
    )
    assert "all selected-pack resources in this account and region" in capsys.readouterr().out

    runner = FakeRunner()
    stack_script.main(
        ["deploy"],
        runner,
        ask=lambda _: "n",
        environ=ENV | {"ALLOW_WRITES": "true", "AGENTIC_IOPS_WRITE_TAG": "MediaOpsManaged=true"},
    )
    assert "resources tagged MediaOpsManaged=true" in capsys.readouterr().out


def test_deploy_without_a_model_stops_before_any_aws_call(capsys):
    runner = FakeRunner()

    assert stack_script.main(["deploy", "--yes"], runner, environ={"AWS_REGION": "us-west-2"}) == 1

    assert runner.calls == []
    assert "AGENT_MODEL_ID" in capsys.readouterr().out


def test_declined_deploy_runs_nothing():
    runner = FakeRunner()

    assert (
        stack_script.main(["deploy"], runner, ask=lambda _: "n", environ=ENV, interactive=True) == 1
    )

    # Only the plan was computed (npm ci, a template-only diff): nothing built or deployed.
    assert runner.ran(" deploy ") == []
    assert [call[1] for call in runner.ran(str(stack_script.CDK_EXECUTABLE))] == ["diff"]


def test_destroy_deletes_the_stack_then_the_runtime_log_groups():
    groups = (
        f"{stack_script.RUNTIME_LOG_PREFIX}abc-DEFAULT {stack_script.RUNTIME_LOG_PREFIX}abc-otel"
    )
    runner = FakeRunner({"describe-log-groups": (0, groups, "")})

    assert stack_script.main(["destroy", "--yes"], runner, environ=ENV) == 0

    order = [i for i, c in enumerate(runner.calls) if "destroy" in c or "delete-log-group" in c]
    assert [runner.calls[i][1] if "destroy" in runner.calls[i] else "logs" for i in order] == [
        "destroy", "logs", "logs",
    ]  # fmt: skip


def test_destroy_of_an_absent_agentic_iops_deletes_nothing(capsys):
    runner = FakeRunner(
        {"describe-stacks": (254, "", NO_STACK), "describe-log-groups": (0, "", "")}
    )  # noqa: E501

    assert stack_script.main(["destroy", "--yes"], runner, environ=ENV) == 0

    assert runner.ran(" destroy ") == [] and runner.ran("delete-log-group") == []
    assert "already absent" in capsys.readouterr().out


def test_a_denied_stack_lookup_is_not_mistaken_for_an_absent_stack(capsys):
    runner = FakeRunner({"describe-stacks": (254, "", DENIED)})

    assert stack_script.main(["destroy", "--yes"], runner, environ=ENV) == 1

    assert runner.ran(" destroy ") == [] and runner.ran("delete-log-group") == []
    assert "Nothing was deleted" in capsys.readouterr().out


def test_a_second_run_after_the_stack_is_gone_cleans_the_remaining_log_groups():
    group = f"{stack_script.RUNTIME_LOG_PREFIX}abc-DEFAULT"
    runner = FakeRunner(
        {"describe-stacks": (254, "", NO_STACK), "describe-log-groups": (0, group, "")}
    )  # noqa: E501

    assert stack_script.main(["destroy", "--yes"], runner, environ=ENV) == 0

    assert runner.ran(" destroy ") == []
    assert len(runner.ran("delete-log-group")) == 1


def test_a_failed_stack_destroy_still_cleans_logs_and_lists_exactly_what_remains(capsys):
    group = f"{stack_script.RUNTIME_LOG_PREFIX}abc-DEFAULT"
    runner = FakeRunner(
        {"describe-log-groups": (0, group, ""), "destroy AgenticIopsStreamingStack": (1, "", "")}
    )  # noqa: E501

    assert stack_script.main(["destroy", "--yes"], runner, environ=ENV) == 1

    out = capsys.readouterr().out
    assert "- CloudFormation stack AgenticIopsStreamingStack" in out
    assert group not in out.split("Remaining resources:")[1]
    assert len(runner.ran("delete-log-group")) == 1


@pytest.mark.parametrize("command", ["deploy", "destroy"])
def test_without_credentials_nothing_is_asked_or_run(command, capsys):
    runner = FakeRunner({"get-caller-identity": (255, "", "Unable to locate credentials")})

    assert (
        stack_script.main([command], runner, ask=lambda _: pytest.fail("asked"), environ=ENV) == 1
    )

    assert len(runner.calls) == 1


def test_destroy_deletes_only_this_runtimes_log_groups_not_similarly_named_ones():
    owned = f"{stack_script.RUNTIME_LOG_PREFIX}AbCdEf1234-DEFAULT"
    runner = FakeRunner({"describe-log-groups": (0, owned, "")})

    assert stack_script.main(["destroy", "--yes"], runner, environ=ENV) == 0

    [lookup] = runner.ran("describe-log-groups")
    assert lookup[lookup.index("--log-group-name-prefix") + 1] == (
        "/aws/bedrock-agentcore/runtimes/AgenticIopsStreamingRuntime-"
    )
    deleted = [c[c.index("--log-group-name") + 1] for c in runner.ran("delete-log-group")]
    assert deleted == [owned]


def test_the_log_prefix_cannot_match_a_similarly_named_runtime():
    foreign = "/aws/bedrock-agentcore/runtimes/AgenticIopsStreamingRuntime2-AbCdEf1234-DEFAULT"
    assert not foreign.startswith(stack_script.RUNTIME_LOG_PREFIX)


def test_the_runtime_name_matches_the_cdk_stack():
    stack = (stack_script.CDK_DIRECTORY / "lib" / "agentic-iops-streaming-stack.ts").read_text()
    assert f"export const RUNTIME_NAME = '{stack_script.RUNTIME_NAME}';" in stack


def test_deploy_attaches_the_invoke_policy_to_the_named_role_only_when_set():
    runner = FakeRunner()
    stack_script.main(
        ["deploy", "--yes"],
        runner,
        environ=ENV | {"AGENTIC_IOPS_INVOKER_ROLE_NAME": "media-ops-operator"},
    )  # noqa: E501
    [deploy] = runner.ran(" deploy AgenticIopsStreamingStack")
    assert "invokerRoleName=media-ops-operator" in deploy

    runner = FakeRunner()
    stack_script.main(["deploy", "--yes"], runner, environ=ENV)
    [deploy] = runner.ran(" deploy AgenticIopsStreamingStack")
    assert not any(argument.startswith("invokerRoleName=") for argument in deploy)


JWT_ENV = {
    "AGENTIC_IOPS_JWT_DISCOVERY_URL": "https://cognito-idp.us-west-2.amazonaws.com/us-west-2_EXAMPLE/.well-known/openid-configuration",
    "AGENTIC_IOPS_JWT_CLIENT_IDS": "example-client-id",
}  # fmt: skip


def test_deploy_passes_jwt_auth_to_cdk_and_names_it_in_the_confirmation(capsys):
    runner = FakeRunner()

    assert (
        stack_script.main(
            ["deploy"], runner, ask=lambda _: "y", environ=ENV | JWT_ENV, interactive=True
        )
        == 0
    )

    [deploy] = runner.ran(" deploy AgenticIopsStreamingStack")
    assert f"jwtDiscoveryUrl={JWT_ENV['AGENTIC_IOPS_JWT_DISCOVERY_URL']}" in deploy
    assert "jwtClientIds=example-client-id" in deploy
    assert "actor = token sub" in capsys.readouterr().out


@pytest.mark.parametrize(
    "extra",
    [
        {"AGENTIC_IOPS_JWT_DISCOVERY_URL": JWT_ENV["AGENTIC_IOPS_JWT_DISCOVERY_URL"]},
        {"AGENTIC_IOPS_JWT_CLIENT_IDS": "example-client-id"},
        JWT_ENV | {"AGENTIC_IOPS_INVOKER_ROLE_NAME": "media-ops-operator"},
    ],
    ids=["url-only", "clients-only", "jwt-and-iam-invoker"],
)
def test_incomplete_or_conflicting_auth_settings_stop_before_any_aws_call(extra, capsys):
    runner = FakeRunner()

    assert stack_script.main(["deploy", "--yes"], runner, environ=ENV | extra) == 1

    assert runner.calls == []
    assert "AGENTIC_IOPS_JWT" in capsys.readouterr().out


def test_the_security_diff_and_the_deploy_name_the_same_models():
    """T60 review: the models are CDK context, so the diff shown before approval synthesizes
    the exact IAM the deploy creates. The stack derives each base model; nothing passes one."""
    runner = FakeRunner()
    env = ENV | {"THUMBNAIL_MODEL_ID": "us.anthropic.claude-haiku-4-5-20251001-v1:0"}

    assert stack_script.main(["deploy", "--yes"], runner, environ=env) == 0

    [diff] = runner.ran(" diff AgenticIopsStreamingStack")
    [deploy] = runner.ran(" deploy AgenticIopsStreamingStack")
    for call in (diff, deploy):
        assert "agentModelId=us.anthropic.claude-sonnet-4-6" in call
        assert "thumbnailModelId=us.anthropic.claude-haiku-4-5-20251001-v1:0" in call
        assert "--parameters" not in call
        assert not any("BaseModelId" in argument for argument in call)


def test_an_unset_thumbnail_model_leaves_the_stack_default():
    runner = FakeRunner()
    assert stack_script.main(["deploy", "--yes"], runner, environ=ENV) == 0
    [deploy] = runner.ran(" deploy AgenticIopsStreamingStack")
    assert not any(argument.startswith("thumbnailModelId=") for argument in deploy)


def test_an_empty_security_diff_deploys_nothing(capsys):
    runner = FakeRunner({"--security-only": (0, "", "")})

    assert stack_script.main(["deploy", "--yes"], runner, environ=ENV) == 1

    assert runner.ran(" deploy AgenticIopsStreamingStack") == []
    assert "security changes: listed above" not in capsys.readouterr().out


def test_the_plan_says_none_when_cdk_reports_no_security_changes(capsys):
    assert stack_script.main(["deploy", "--yes"], FakeRunner(), environ=ENV) == 0
    assert "security changes: none (cdk diff: no security-related changes)" in (
        capsys.readouterr().out
    )


def test_a_bootstrap_with_another_qualifier_stops_before_anything_is_built(capsys):
    other = (0, '{"status": "UPDATE_COMPLETE", "qualifier": "custom1"}', "")
    runner = FakeRunner({"--stack-name CDKToolkit": other})

    assert stack_script.main(["deploy", "--yes"], runner, environ=ENV) == 1

    assert runner.ran("npm ci") == [] and runner.ran(" deploy AgenticIopsStreamingStack") == []
    assert "has qualifier custom1" in capsys.readouterr().out


def test_destroy_deletes_a_stack_a_failed_deploy_left_in_rollback_complete(capsys):
    """RB14: the live failure rolled back; `just destroy agentic-iops-streaming` is how to clear
    it."""
    runner = FakeRunner({"--stack-name AgenticIopsStreamingStack": (0, "ROLLBACK_COMPLETE\n", "")})

    assert stack_script.main(["destroy", "--yes"], runner, environ=ENV) == 0

    assert runner.ran("destroy AgenticIopsStreamingStack --force")
    assert "AgenticIopsStreamingStack (ROLLBACK_COMPLETE)" in capsys.readouterr().out
