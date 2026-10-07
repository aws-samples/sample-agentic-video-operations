"""Every event is a StreamEvent and raw tool output never streams
(extend_agentic_iops_streaming.md §1, §6)."""

import json
import logging

from agentic_iops_test_setup import COSTED_MODEL_ID, build_agentic_iops, only, types
from channel_test_pack import RAW_OUTPUT_MARKER
from scripted_model import GatedModel, ScriptedModel, call, say

from media_ops_contracts.stream_event import STREAM_EVENT_ADAPTER

DESCRIBE = call("describe_channel", "use-1", channel_id="ch-1")


def test_a_read_turn_streams_valid_events_without_raw_tool_output(tmp_path, caplog):
    iops = build_agentic_iops(
        tmp_path,
        ScriptedModel([DESCRIBE], [say("ch-1 is RUNNING.")]),
        model_id=COSTED_MODEL_ID,
    )

    with caplog.at_level(logging.INFO, logger="agentic_iops_streaming"):
        events = iops.ask("Is ch-1 healthy?")

    payloads = [
        STREAM_EVENT_ADAPTER.dump_python(
            STREAM_EVENT_ADAPTER.validate_python(event),
            mode="json",
        )
        for event in events
    ]
    assert [STREAM_EVENT_ADAPTER.validate_python(payload).type for payload in payloads] == types(
        events
    )
    assert types(events) == ["task_started", "tool_called", "usage_reported", "final_answer"]
    assert only(events, "tool_called").read_only is True
    assert only(events, "task_started").specialist == "testlive"
    assert RAW_OUTPUT_MARKER not in json.dumps(payloads)
    assert RAW_OUTPUT_MARKER not in caplog.text
    assert '"session.id": "session-a"' in caplog.text
    assert '"pack.name": "testlive", "tool.name": "describe_channel"' in caplog.text


def test_a_turn_reports_its_accumulated_usage(tmp_path, caplog):
    per_call = {
        "inputTokens": 1,
        "outputTokens": 1,
        "totalTokens": 2,
        "cacheReadInputTokens": 3,
        "cacheWriteInputTokens": 4,
    }
    iops = build_agentic_iops(
        tmp_path,
        ScriptedModel([DESCRIBE], [say("ch-1 is RUNNING.")], usage=per_call),
        model_id=COSTED_MODEL_ID,
    )

    with caplog.at_level(logging.INFO, logger="agentic_iops_streaming"):
        events = iops.ask("Is ch-1 healthy?")

    usage = only(events, "usage_reported")
    # the ScriptedModel reports 1 input and 1 output token per model call; two calls ran
    assert (
        usage.input_tokens,
        usage.output_tokens,
        usage.total_tokens,
        usage.cache_read_input_tokens,
        usage.cache_write_input_tokens,
    ) == (2, 2, 4, 6, 8)
    assert usage.estimated_usd == 0.000036
    assert usage.rates_confirmed is False
    assert '"tokens.input": 2, "tokens.output": 2' in caplog.text
    assert '"tokens.cache_read_input": 6, "tokens.cache_write_input": 8' in caplog.text


def test_an_unknown_exact_model_id_keeps_usage_and_omits_the_cost(tmp_path):
    unknown_model = ".".join(("us", "amazon", "nova-pro-v1:0"))
    iops = build_agentic_iops(
        tmp_path,
        ScriptedModel([say("Done.")]),
        model_id=unknown_model,
    )

    usage = only(iops.ask("Status?"), "usage_reported")

    assert usage.model_id == unknown_model
    assert usage.estimated_usd is None


def test_a_loaded_skill_is_logged_by_name(tmp_path, caplog):
    load = call("load_skill", "use-1", name="diagnose-signal-path")
    iops = build_agentic_iops(tmp_path, ScriptedModel([load], [say("Walked the path.")]))

    with caplog.at_level(logging.INFO, logger="agentic_iops_streaming"):
        events = iops.ask("Why is ch-1 on slate?")

    assert only(events, "tool_called").tool == "load_skill"
    assert '"skill.name": "diagnose-signal-path"' in caplog.text
    assert "first hop that is unhealthy" not in caplog.text


def test_load_skill_returns_the_body_and_lists_names_when_unknown(tmp_path):
    iops = build_agentic_iops(tmp_path, ScriptedModel())
    [load_skill] = [tool for tool in iops.iops.tools if tool.tool_name == "load_skill"]

    assert "signal path" in iops.iops.system_prompt
    assert "first hop that is unhealthy" in load_skill("diagnose-signal-path")
    assert "diagnose-signal-path" in load_skill("no-such-skill")


def test_going_over_the_tool_budget_ends_the_turn_with_an_error(tmp_path):
    model = ScriptedModel([DESCRIBE], [call("describe_channel", "use-2", channel_id="ch-1")])
    iops = build_agentic_iops(tmp_path, model, budget=1, model_id=COSTED_MODEL_ID)

    events = iops.ask("Check ch-1 twice.")

    assert types(events)[-2:] == ["usage_reported", "error"]
    assert only(events, "error").kind == "InvalidRequest"
    assert "final_answer" not in types(events)


def test_events_reach_the_caller_while_the_turn_is_still_running(tmp_path):
    model = GatedModel([DESCRIBE], [say("ch-1 is RUNNING.")], gate_at=2)
    iops = build_agentic_iops(tmp_path, model, model_id=COSTED_MODEL_ID)
    stream = iops.stream("Is ch-1 healthy?")

    assert next(stream).type == "task_started"
    assert next(stream).type == "tool_called"
    assert model.waiting.wait(5)  # the second model call is blocked: the turn is not over
    assert not model.gate.is_set()

    model.gate.set()
    assert types(list(stream)) == ["usage_reported", "final_answer"]
    assert model.opened_by_test  # the events above arrived before the turn could finish
