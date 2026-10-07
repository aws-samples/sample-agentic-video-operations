"""The executable offline agentic-iops-streaming evaluation suite."""

import json

import pytest
from load_eval_scenarios import load_eval_scenarios
from run_eval_scenario import ROOT, run_scenario

pytestmark = pytest.mark.eval
SCENARIOS = ROOT / "samples/agentic-iops-streaming/tests/scenarios"


def test_all_agentic_iops_scenarios(tmp_path, request):
    scenarios = load_eval_scenarios(SCENARIOS)
    assert len(scenarios) == 8
    results = [run_scenario(scenario, tmp_path) for scenario in scenarios]
    output = ROOT / ".cache" / "eval-results.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps([result.model_dump() for result in results], indent=2) + "\n")

    terminal = request.config.pluginmanager.get_plugin("terminalreporter")
    terminal.write_line(
        "\nscenario                         pass  tokens(in/out)  tools  writes  verified  latency"
    )
    for result in results:
        terminal.write_line(
            f"{result.scenario:<32} {'yes' if result.passed else 'NO ':<5} "
            f"{result.input_tokens:>4}/{result.output_tokens:<4} "
            f"{len(result.tool_calls):>5} {result.writes_attempted:>7} "
            f"{sum(item.verified for item in result.verifications):>9} "
            f"{result.latency_ms:>7.2f} ms"
        )
    failures = [
        f"{result.scenario}: {'; '.join(result.failures)}"
        for result in results
        if not result.passed
    ]
    assert not failures, "\n".join(failures)
