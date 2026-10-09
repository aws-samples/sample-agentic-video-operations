import json
from pathlib import Path

from hls_fixture_mutations import MUTATIONS, apply_mutation

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPOSITORY_ROOT / "fixtures"


def load_scenario_files(scenario: str) -> dict:
    return {
        path.name.removesuffix(".json"): json.loads(path.read_text())
        for path in sorted((FIXTURES / scenario).glob("*.json"))
    }


def test_every_mutation_has_a_committed_scenario() -> None:
    for name in MUTATIONS:
        path = FIXTURES / name / "http.exchanges.json"
        assert path.is_file(), f"fixtures/{name} is missing; regenerate with mutate_hls_fixtures"


def test_mutations_are_deterministic_and_leave_the_base_untouched() -> None:
    for name, (base_name, _) in MUTATIONS.items():
        base = load_scenario_files(base_name)
        snapshot = json.dumps(base, sort_keys=True)
        first = apply_mutation(base, name)
        second = apply_mutation(base, name)
        assert first == second, name
        assert first != base, name
        assert json.dumps(base, sort_keys=True) == snapshot, name


def test_committed_scenarios_match_their_mutation() -> None:
    for name, (base_name, _) in MUTATIONS.items():
        committed = load_scenario_files(name)
        expected = apply_mutation(load_scenario_files(base_name), name)
        assert committed == expected, (
            f"fixtures/{name} drifted from mutation {name!r};"
            " regenerate with scripts/mutate_hls_fixtures.py"
        )
