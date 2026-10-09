"""The agent's model caches its stable prefix: the tool schemas, the system prompt, the turn.

A live three-call turn repeats a stable prefix of about 4.1K input tokens per call. It cost
$0.051 before caching, $0.036 on the first cached turn, and $0.018 warm. Bedrock caches up
to a cachePoint; these tests format a request offline, with no model call, and check where
the points are.
"""

import json
from pathlib import Path

from strands.models import BedrockModel

from agentic_iops_streaming.bootstrap.create_agentic_iops import (
    create_agentic_iops,
    create_bedrock_model,
)
from agentic_iops_streaming.settings.runtime_settings import AgenticIopsSettings

MODEL = "us.anthropic.claude-sonnet-4-6"
MINIMUM_CACHED_TOKENS = 1024  # Sonnet's smallest cacheable prefix on Bedrock; Haiku needs more


FIXTURES = Path(__file__).resolve().parents[4] / "fixtures"


def agentic_iops(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO", "1")  # replayed packs: their real tool schemas, no AWS client
    monkeypatch.setenv("FIXTURES_DIR", str(FIXTURES))
    # Building a boto3 client resolves credentials; placeholders keep that off the network.
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    settings = AgenticIopsSettings(agent_model_id=MODEL, session_dir=tmp_path / "sessions")
    return settings, create_agentic_iops(
        settings, model=BedrockModel(model_id=MODEL, region_name="us-west-2")
    )


def formatted_request(model, iops) -> dict:
    return model.format_request(
        [{"role": "user", "content": [{"text": "List the channels."}]}],
        tool_specs=[tool.tool_spec for tool in iops.tools],
        system_prompt_content=[{"text": iops.system_prompt}],
    )


def test_the_agent_model_caches_the_tools_the_system_prompt_and_the_turn(tmp_path, monkeypatch):
    settings, iops = agentic_iops(tmp_path, monkeypatch)

    request = formatted_request(create_bedrock_model(settings), iops)

    assert "cachePoint" in request["toolConfig"]["tools"][-1]
    assert "cachePoint" in request["system"][-1]
    assert "cachePoint" in request["messages"][-1]["content"][-1]


def test_a_model_without_the_cache_config_sends_no_cache_point(tmp_path, monkeypatch):
    """What every request looked like before: nothing marked, so nothing cached."""
    _, iops = agentic_iops(tmp_path, monkeypatch)

    request = formatted_request(BedrockModel(model_id=MODEL, region_name="us-west-2"), iops)

    assert '"cachePoint"' not in json.dumps(request)


def test_the_tool_schemas_alone_are_long_enough_to_be_cached(tmp_path, monkeypatch):
    """Below the minimum, Bedrock ignores a cache point. About four characters per token."""
    _, iops = agentic_iops(tmp_path, monkeypatch)

    schema_characters = len(json.dumps([tool.tool_spec for tool in iops.tools]))

    assert schema_characters // 4 >= MINIMUM_CACHED_TOKENS
