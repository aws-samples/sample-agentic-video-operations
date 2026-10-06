import json
from pathlib import Path

from hls_fixture_mutations import MUTATIONS, apply_mutation

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BASE = json.loads((REPOSITORY_ROOT / "fixtures/hls_clean_vod/http.exchanges.json").read_text())


def test_every_mutation_has_a_committed_scenario() -> None:
    for name in MUTATIONS:
        path = REPOSITORY_ROOT / "fixtures" / name / "http.exchanges.json"
        assert path.is_file(), f"fixtures/{name} is missing; regenerate with mutate_hls_fixtures"


def test_mutations_are_deterministic_and_leave_the_base_untouched() -> None:
    snapshot = json.dumps(BASE, sort_keys=True)
    for name in MUTATIONS:
        first = apply_mutation(BASE, name)
        second = apply_mutation(BASE, name)
        assert first == second, name
        assert first != BASE, name
    assert json.dumps(BASE, sort_keys=True) == snapshot


def test_committed_scenarios_match_their_mutation() -> None:
    for name in MUTATIONS:
        committed = json.loads(
            (REPOSITORY_ROOT / "fixtures" / name / "http.exchanges.json").read_text()
        )
        assert committed == apply_mutation(BASE, name), (
            f"fixtures/{name} drifted from mutation {name!r};"
            " regenerate with scripts/mutate_hls_fixtures.py"
        )
