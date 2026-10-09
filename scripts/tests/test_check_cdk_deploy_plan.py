"""The deploy plan's bootstrap and security-diff checks.

A healthy CDKToolkit with another qualifier, or an old version, can't serve these apps; a
security diff that printed nothing can't back an approval.
"""

import json
import subprocess

import check_cdk_deploy_plan as plan

TARGET = "aws://111122223333/us-west-2"
CHANGES = "Stack AgenticIopsStreamingStack\nIAM Statement Changes\n[+] Allow sts:AssumeRole\n"


class FakeRunner:
    def __init__(self, *, stack=None, version=(0, "21\n", ""), diff=(0, "", CHANGES)):
        default = (0, json.dumps({"status": "UPDATE_COMPLETE", "qualifier": "hnb659fds"}), "")
        self.stack, self.version, self.diff = stack or default, version, diff
        self.calls = []

    def __call__(self, arguments, cwd, capture):
        self.calls.append(" ".join(arguments))
        joined = self.calls[-1]
        if "--stack-name CDKToolkit" in joined:
            answer = self.stack
        elif "ssm get-parameter" in joined:
            answer = self.version
        else:
            answer = self.diff
        return subprocess.CompletedProcess(arguments, *answer)


def bootstrap(runner, tmp_path):
    return plan.check_cdk_bootstrap(runner, "us-west-2", "111122223333", tmp_path)


def stack(**fields):
    return (0, json.dumps(fields), "")


def test_the_default_bootstrap_is_found_with_its_qualifier_and_version(tmp_path):
    runner = FakeRunner()
    assert bootstrap(runner, tmp_path) == "found (CDKToolkit, qualifier hnb659fds, version 21)"
    assert any("--name /cdk-bootstrap/hnb659fds/version" in call for call in runner.calls)


def test_a_custom_qualifier_on_the_stack_stops_the_deploy(tmp_path, capsys):
    runner = FakeRunner(stack=stack(status="UPDATE_COMPLETE", qualifier="custom1"))

    assert bootstrap(runner, tmp_path) is None

    output = capsys.readouterr().out
    assert f"CDKToolkit in {TARGET} has qualifier custom1" in output
    assert "deploys through the hnb659fds bootstrap resources" in output
    assert "Nothing was built or deployed." in output


def test_a_legacy_bootstrap_without_a_qualifier_stops_the_deploy(tmp_path, capsys):
    assert (
        bootstrap(FakeRunner(stack=stack(status="CREATE_COMPLETE", qualifier=None)), tmp_path)
        is None
    )
    assert "has no Qualifier (legacy)" in capsys.readouterr().out


def test_the_app_qualifier_comes_from_cdk_json_when_it_sets_one(tmp_path):
    context = {"context": {"@aws-cdk/core:bootstrapQualifier": "custom1"}}
    (tmp_path / "cdk.json").write_text(json.dumps(context))
    runner = FakeRunner(stack=stack(status="UPDATE_COMPLETE", qualifier="custom1"))

    assert bootstrap(runner, tmp_path) == "found (CDKToolkit, qualifier custom1, version 21)"
    assert any("/cdk-bootstrap/custom1/version" in call for call in runner.calls)


def test_a_bootstrap_in_another_region_is_missing_here_and_names_this_region(tmp_path, capsys):
    missing = "An error occurred (ValidationError) when calling DescribeStacks: Stack with id CDKToolkit does not exist"  # noqa: E501
    runner = FakeRunner(stack=(254, "", missing))

    assert bootstrap(runner, tmp_path) is None

    assert "--region us-west-2" in runner.calls[0]
    output = capsys.readouterr().out
    assert f"CDK bootstrap: missing in {TARGET}" in output
    assert f"npx cdk bootstrap {TARGET}" in output


def test_a_missing_or_old_bootstrap_version_stops_the_deploy(tmp_path, capsys):
    not_found = "An error occurred (ParameterNotFound) when calling the GetParameter operation: "
    assert bootstrap(FakeRunner(version=(254, "", not_found)), tmp_path) is None
    assert "/cdk-bootstrap/hnb659fds/version is missing" in capsys.readouterr().out

    assert bootstrap(FakeRunner(version=(0, "5\n", "")), tmp_path) is None
    assert "needs version 6 or later" in capsys.readouterr().out

    assert bootstrap(FakeRunner(version=(0, "\n", "")), tmp_path) is None


def test_an_unusable_bootstrap_status_still_stops_the_deploy(tmp_path, capsys):
    runner = FakeRunner(stack=stack(status="ROLLBACK_COMPLETE", qualifier="hnb659fds"))
    assert bootstrap(runner, tmp_path) is None
    assert "CDKToolkit is ROLLBACK_COMPLETE" in capsys.readouterr().out


def diff(runner, tmp_path):
    return plan.show_security_diff(
        runner, tmp_path / "cdk", "AgenticIopsStreamingStack", [], tmp_path
    )


def test_a_security_diff_with_changes_is_printed_and_listed_above(tmp_path, capsys):
    assert diff(FakeRunner(diff=(0, "", CHANGES)), tmp_path) == "listed above"
    assert "[+] Allow sts:AssumeRole" in capsys.readouterr().out


def test_cdk_saying_there_are_no_security_changes_is_shown_as_none(tmp_path, capsys):
    said = (
        "Stack AgenticIopsStreamingStack\nThere were no security-related changes (limitations: …)\n"
    )
    assert diff(FakeRunner(diff=(0, "", said)), tmp_path) == (
        "none (cdk diff: no security-related changes)"
    )
    assert "There were no security-related changes" in capsys.readouterr().out


def test_an_empty_security_diff_cannot_back_an_approval(tmp_path, capsys):
    assert diff(FakeRunner(diff=(0, "", "")), tmp_path) is None
    assert diff(FakeRunner(diff=(0, "  \n", "\n")), tmp_path) is None
    assert "printed nothing, so nothing was built or deployed" in capsys.readouterr().out


def test_a_failed_security_diff_stops_and_shows_why(tmp_path, capsys):
    assert diff(FakeRunner(diff=(1, "", "synth failed")), tmp_path) is None
    output = capsys.readouterr().out
    assert "synth failed" in output and "Could not compute the security diff" in output


# Exit 0 with output is not enough. The output must be CDK's result for this
# stack: `Stack <name>`, then the "no changes" sentence or a security-change section.
NODE_WARNING = "(node:4242) [DEP0040] DeprecationWarning: The `punycode` module is deprecated.\n"
NOTICE = "NOTICES\n\n31885\tbootstrap: a new version is available\n"


def test_a_warning_or_notice_alone_cannot_back_an_approval(tmp_path, capsys):
    assert diff(FakeRunner(diff=(0, "", NODE_WARNING)), tmp_path) is None
    assert diff(FakeRunner(diff=(0, NOTICE, "")), tmp_path) is None
    assert "no security diff for AgenticIopsStreamingStack" in capsys.readouterr().out


def test_a_diff_for_another_stack_cannot_back_an_approval(tmp_path):
    other = "Stack OtherStack\nThere were no security-related changes\n"
    assert diff(FakeRunner(diff=(0, "", other)), tmp_path) is None
    prefix = "Stack AgenticIopsStreamingStackOld\nIAM Statement Changes\n"
    assert diff(FakeRunner(diff=(0, "", prefix)), tmp_path) is None


def test_the_stack_line_alone_or_unrelated_text_after_it_is_not_a_result(tmp_path):
    assert diff(FakeRunner(diff=(0, "", "Stack AgenticIopsStreamingStack\n")), tmp_path) is None
    after = "Stack AgenticIopsStreamingStack\n" + NODE_WARNING
    assert diff(FakeRunner(diff=(0, "", after)), tmp_path) is None


def test_each_cdk_security_section_counts_as_listed_changes(tmp_path):
    for section in ("IAM Statement Changes", "IAM Policy Changes", "Security Group Changes"):
        shown = NODE_WARNING + f"Stack AgenticIopsStreamingStack\n{section}\n┌───┐\n"
        assert diff(FakeRunner(diff=(0, "", shown)), tmp_path) == "listed above"


def test_colored_output_is_read_without_its_escape_codes(tmp_path):
    colored = (
        "Stack \x1b[1mAgenticIopsStreamingStack\x1b[22m\n"
        "\x1b[32mThere were no security-related changes\x1b[39m\n"
    )
    assert diff(FakeRunner(diff=(0, "", colored)), tmp_path) == (
        "none (cdk diff: no security-related changes)"
    )


def test_a_later_stacks_changes_cannot_authorize_this_stack(tmp_path):
    """The result must be in this stack's own section, not a later one's."""
    later_changes = (
        "Stack AgenticIopsStreamingStack\nStack OtherStack\nIAM Statement Changes\n┌───┐\n"
    )
    assert diff(FakeRunner(diff=(0, "", later_changes)), tmp_path) is None
    later_none = (
        "Stack AgenticIopsStreamingStack\nStack OtherStack\n"
        "There were no security-related changes\n"
    )
    assert diff(FakeRunner(diff=(0, "", later_none)), tmp_path) is None


def test_this_stacks_own_section_counts_even_when_another_stack_follows(tmp_path):
    shown = (
        "Stack AgenticIopsStreamingStack\nThere were no security-related changes\n"
        "Stack OtherStack\nIAM Statement Changes\n"
    )
    assert diff(FakeRunner(diff=(0, "", shown)), tmp_path) == (
        "none (cdk diff: no security-related changes)"
    )
    earlier = (
        "Stack OtherStack\nThere were no security-related changes\n"
        "Stack AgenticIopsStreamingStack\nIAM Policy Changes\n"
    )
    assert diff(FakeRunner(diff=(0, "", earlier)), tmp_path) == "listed above"
