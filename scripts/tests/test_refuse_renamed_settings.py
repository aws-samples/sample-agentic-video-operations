"""A setting still named HUB_* stops the deploy before any AWS call.

The sample renamed every HUB_* setting to AGENTIC_IOPS_*, and the deploy reads only the new names.
So a leftover old name failed open: HUB_WRITE_TAG silently dropped the write tag scope, and
HUB_JWT_* deployed IAM auth, where the runtime trusts the caller-supplied actor header.
"""

import re
from pathlib import Path

import manage_agentic_iops_streaming_stack as stack_script
import pytest
from renamed_settings import NEW_PREFIX, OLD_PREFIX, RENAMED, find_renamed_settings
from test_manage_agentic_iops_streaming_stack import ENV, FakeRunner

ROOT = Path(__file__).resolve().parents[2]
NEW_NAMES = sorted(
    set(re.findall(r"^#? ?(AGENTIC_IOPS_[A-Z_]+)=", (ROOT / ".env.example").read_text(), re.M))
)
# The settings that had a pre-rename name. A setting added since (AGENTIC_IOPS_PORT) has none,
# so the old names come from the rule itself, not from every documented setting.
OLD_NAMES = sorted(RENAMED)


def test_the_renamed_settings_are_the_nine_that_existed_before_the_rename():
    assert len(OLD_NAMES) == 9 and "HUB_WRITE_TAG" in OLD_NAMES


@pytest.mark.parametrize("old", OLD_NAMES)
def test_a_deploy_with_an_old_setting_name_stops_before_any_aws_call(old, capsys):
    runner = FakeRunner()
    new = old.replace("HUB_", "AGENTIC_IOPS_", 1)

    assert stack_script.main(["deploy", "--yes"], runner, environ=ENV | {old: "x"}) == 1

    assert runner.calls == []
    out = capsys.readouterr().out
    assert f"{old} -> {new}" in out and "Nothing was deployed" in out


def test_a_stale_hub_write_tag_says_the_write_scope_would_be_lost(capsys):
    runner = FakeRunner()
    environ = ENV | {"ALLOW_WRITES": "true", "HUB_WRITE_TAG": "MediaOpsManaged=true"}

    assert stack_script.main(["deploy", "--yes"], runner, environ=environ) == 1

    assert runner.calls == []
    assert "writes would not be tag-scoped" in capsys.readouterr().out


def test_a_stale_hub_jwt_setting_says_iam_auth_would_trust_the_actor_header(capsys):
    environ = ENV | {"HUB_JWT_DISCOVERY_URL": "https://issuer.example.com/.well-known/x"}

    assert stack_script.main(["deploy", "--yes"], FakeRunner(), environ=environ) == 1

    assert "caller-supplied actor header" in capsys.readouterr().out


def test_the_new_name_beside_the_old_one_is_still_refused():
    """Both set is still a stale .env: the old line may hold the value someone meant."""
    found = find_renamed_settings({"HUB_WRITE_TAG": "a=b", "AGENTIC_IOPS_WRITE_TAG": "a=b"})

    assert found == {"HUB_WRITE_TAG": "AGENTIC_IOPS_WRITE_TAG"}


def test_destroy_is_not_blocked_by_an_old_name(capsys):
    """Teardown reads no HUB_* setting, and must never be what keeps billing running."""
    runner = FakeRunner({"describe-log-groups": (0, "", "")})

    assert (
        stack_script.main(["destroy", "--yes"], runner, environ=ENV | {"HUB_WRITE_TAG": "x"}) == 0
    )


def test_the_doctor_and_the_deploy_name_the_same_renames():
    import check_prerequisites as doctor

    result = doctor.check_renamed_settings({"HUB_TOOL_BUDGET": "8"})

    assert "HUB_TOOL_BUDGET -> AGENTIC_IOPS_TOOL_BUDGET" in result.fix


def test_another_tools_hub_variable_is_not_one_of_ours():
    """GitHub's `hub` CLI reads HUB_PROTOCOL and HUB_VERBOSE: they stop nothing."""
    assert find_renamed_settings({"HUB_PROTOCOL": "https", "HUB_VERBOSE": "1"}) == {}


def test_the_deploy_and_the_runtime_refuse_the_same_names():
    import renamed_settings as deploy

    from agentic_iops_streaming.settings import refuse_renamed_settings as runtime

    assert runtime.RENAMED == deploy.RENAMED
    # Every renamed setting is still documented under its new name; settings added since have
    # no old name, so this is a subset, not an equality.
    assert {NEW_PREFIX + old.removeprefix(OLD_PREFIX) for old in RENAMED} <= set(NEW_NAMES)


def test_a_setting_added_since_the_rename_is_not_refused_under_a_made_up_old_name():
    assert "AGENTIC_IOPS_PORT" in NEW_NAMES
    assert find_renamed_settings({"HUB_PORT": "8091"}) == {}
