"""The runtime refuses to start while a setting is still named HUB_*.

Locally and in a container, an old name would otherwise be ignored: HUB_LOCAL_MODE or
HUB_JWT_ISSUER silently changes who the runtime believes the caller is.
"""

import pytest
from pydantic import ValidationError

from agentic_iops_streaming.settings.refuse_renamed_settings import (
    NEW_PREFIX,
    OLD_PREFIX,
    RENAMED,
)
from agentic_iops_streaming.settings.runtime_settings import AgenticIopsSettings

RENAMES = tuple((old, NEW_PREFIX + old.removeprefix(OLD_PREFIX)) for old in sorted(RENAMED))


@pytest.mark.parametrize(("old", "new"), RENAMES)
def test_an_old_setting_name_stops_startup_and_names_its_new_name(monkeypatch, old, new):
    monkeypatch.setenv(old, "x")

    with pytest.raises(ValidationError) as refused:
        AgenticIopsSettings(agent_model_id="us.anthropic.claude-sonnet-4-6")

    assert f"{old} -> {new}" in str(refused.value)


def test_no_old_name_starts_normally(monkeypatch):
    monkeypatch.setenv("AGENTIC_IOPS_TOOL_BUDGET", "8")

    assert AgenticIopsSettings(agent_model_id="m").agentic_iops_tool_budget == 8
