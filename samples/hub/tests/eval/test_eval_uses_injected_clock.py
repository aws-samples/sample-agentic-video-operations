"""Approval evals use their injected clock, independent of wall time."""

import ast
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from load_eval_scenarios import load_eval_scenarios
from run_eval_scenario import ROOT, run_scenario

pytestmark = pytest.mark.eval
SCENARIOS = ROOT / "samples/hub/tests/scenarios"
PACK_WRITE_PATHS = [
    Path("samples/mediaconnect/src/mediaconnect_mcp/domain_pack.py"),
    Path("samples/mediaconnect/src/mediaconnect_mcp/tool_surface/create_write_tools.py"),
    Path("samples/medialive/src/medialive_mcp/domain_pack.py"),
    Path("samples/medialive/src/medialive_mcp/tool_surface/create_write_tools.py"),
]


class FarFutureDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2099, 1, 1, tzinfo=tz or UTC)


def test_write_scenario_passes_when_wall_clock_is_far_in_the_future(tmp_path):
    scenario = next(
        item for item in load_eval_scenarios(SCENARIOS) if item.name == "srt_packet_loss"
    )

    with patch("media_ops_contracts.read_utc_now.datetime", FarFutureDateTime):
        result = run_scenario(scenario, tmp_path)

    assert result.passed, result.failures
    assert len(result.verifications) == 1
    assert result.verifications[0].verified


@pytest.mark.parametrize("relative_path", PACK_WRITE_PATHS)
def test_pack_write_paths_do_not_read_the_wall_clock_directly(relative_path):
    tree = ast.parse((ROOT / relative_path).read_text())
    direct_reads = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "now"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "datetime"
    ]

    assert direct_reads == []
