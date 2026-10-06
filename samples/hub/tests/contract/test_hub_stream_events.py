"""Every event is a StreamEvent and raw tool output never streams (extend_the_hub.md §1, §6)."""

import logging

from channel_test_pack import RAW_OUTPUT_MARKER
from hub_test_setup import build_hub, only, types
from media_ops_contracts.stream_event import STREAM_EVENT_ADAPTER, encode_stream_event
from scripted_model import GatedModel, ScriptedModel, call, say

DESCRIBE = call("describe_channel", "use-1", channel_id="ch-1")


def test_a_read_turn_streams_valid_events_without_raw_tool_output(tmp_path, caplog):
    hub = build_hub(tmp_path, ScriptedModel([DESCRIBE], [say("ch-1 is RUNNING.")]))

    with caplog.at_level(logging.INFO, logger="media_ops_hub"):
        events = hub.ask("Is ch-1 healthy?")

    encoded = [encode_stream_event(event) for event in events]
    assert [STREAM_EVENT_ADAPTER.validate_json(line).type for line in encoded] == types(events)
    assert types(events) == ["task_started", "tool_called", "final_answer", "usage_reported"]
    assert only(events, "tool_called").read_only is True
    assert only(events, "task_started").specialist == "testlive"
    assert RAW_OUTPUT_MARKER not in "".join(encoded)
    assert RAW_OUTPUT_MARKER not in caplog.text
    assert '"session.id": "session-a"' in caplog.text
    assert '"pack.name": "testlive", "tool.name": "describe_channel"' in caplog.text


def test_a_turn_reports_its_accumulated_usage(tmp_path, caplog):
    hub = build_hub(tmp_path, ScriptedModel([DESCRIBE], [say("ch-1 is RUNNING.")]))

    with caplog.at_level(logging.INFO, logger="media_ops_hub"):
        events = hub.ask("Is ch-1 healthy?")

    usage = only(events, "usage_reported")
    # the ScriptedModel reports 1 input and 1 output token per model call; two calls ran
    assert (usage.input_tokens, usage.output_tokens, usage.total_tokens) == (2, 2, 4)
    assert usage.estimated_usd is None  # the test hub sets no AGENT_MODEL_ID
    assert '"tokens.input": 2, "tokens.output": 2' in caplog.text


def test_a_loaded_skill_is_logged_by_name(tmp_path, caplog):
    load = call("load_skill", "use-1", name="diagnose-signal-path")
    hub = build_hub(tmp_path, ScriptedModel([load], [say("Walked the path.")]))

    with caplog.at_level(logging.INFO, logger="media_ops_hub"):
        events = hub.ask("Why is ch-1 on slate?")

    assert only(events, "tool_called").tool == "load_skill"
    assert '"skill.name": "diagnose-signal-path"' in caplog.text
    assert "first hop that is unhealthy" not in caplog.text


def test_load_skill_returns_the_body_and_lists_names_when_unknown(tmp_path):
    hub = build_hub(tmp_path, ScriptedModel())
    [load_skill] = [tool for tool in hub.hub.tools if tool.tool_name == "load_skill"]

    assert "signal path" in hub.hub.system_prompt
    assert "first hop that is unhealthy" in load_skill("diagnose-signal-path")
    assert "diagnose-signal-path" in load_skill("no-such-skill")


def test_going_over_the_tool_budget_ends_the_turn_with_an_error(tmp_path):
    model = ScriptedModel([DESCRIBE], [call("describe_channel", "use-2", channel_id="ch-1")])
    hub = build_hub(tmp_path, model, budget=1)

    events = hub.ask("Check ch-1 twice.")

    assert types(events)[-2:] == ["error", "usage_reported"]
    assert only(events, "error").kind == "InvalidRequest"
    assert "final_answer" not in types(events)


def test_events_reach_the_caller_while_the_turn_is_still_running(tmp_path):
    model = GatedModel([DESCRIBE], [say("ch-1 is RUNNING.")], gate_at=2)
    hub = build_hub(tmp_path, model)
    stream = hub.stream("Is ch-1 healthy?")

    assert next(stream).type == "task_started"
    assert next(stream).type == "tool_called"
    assert model.waiting.wait(5)  # the second model call is blocked: the turn is not over
    assert not model.gate.is_set()

    model.gate.set()
    assert types(list(stream)) == ["final_answer", "usage_reported"]
    assert model.opened_by_test  # the events above arrived before the turn could finish
