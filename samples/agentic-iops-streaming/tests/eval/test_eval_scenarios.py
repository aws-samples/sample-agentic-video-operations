"""The executable offline agentic-iops-streaming evaluation suite."""

import json

import pytest
from load_eval_scenarios import load_eval_scenarios
from run_eval_scenario import ROOT, count_tool_errors, run_scenario

pytestmark = pytest.mark.eval
SCENARIOS = ROOT / "samples/agentic-iops-streaming/tests/scenarios"


def test_tool_errors_are_counted_once_per_tool_use():
    messages = [
        {
            "content": [
                {"toolResult": {"toolUseId": "read-1", "status": "success"}},
                {"toolResult": {"toolUseId": "read-2", "status": "error"}},
            ]
        },
        {
            "content": [
                {"toolResult": {"toolUseId": "read-2", "status": "error"}},
                {"toolResult": {"toolUseId": "read-3", "status": "error"}},
            ]
        },
    ]

    assert count_tool_errors(messages) == 2


def test_all_agentic_iops_scenarios(tmp_path, request):
    scenarios = load_eval_scenarios(SCENARIOS)
    assert len(scenarios) == 10
    results = [run_scenario(scenario, tmp_path) for scenario in scenarios]
    output = ROOT / ".cache" / "eval-results.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps([result.model_dump() for result in results], indent=2) + "\n")

    terminal = request.config.pluginmanager.get_plugin("terminalreporter")
    terminal.write_line(
        "\nscenario                         pass  tokens(in/out)  "
        "tools  writes  errors  verified  latency"
    )
    for result in results:
        terminal.write_line(
            f"{result.scenario:<32} {'yes' if result.passed else 'NO ':<5} "
            f"{result.input_tokens:>4}/{result.output_tokens:<4} "
            f"{len(result.tool_calls):>5} {result.writes_attempted:>7} "
            f"{result.tool_errors:>7} "
            f"{sum(item.verified for item in result.verifications):>9} "
            f"{result.latency_ms:>7.2f} ms"
        )
    failures = [
        f"{result.scenario}: {'; '.join(result.failures)}"
        for result in results
        if not result.passed
    ]
    assert not failures, "\n".join(failures)
