"""Derive a broken HLS Doctor scenario from its recorded base fixture.

Usage:
    uv run python scripts/mutate_hls_fixtures.py --mutation hls_broken_map [--out <scenario>]

The base scenario comes from the mutation registry, so a derived scenario is
always regenerated from the same base it is documented against.
"""

import argparse
import json
from pathlib import Path

from hls_fixture_mutations import MUTATIONS, apply_mutation, dump_fixture

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def load_scenario_files(scenario: str) -> dict:
    files = {}
    for path in sorted((FIXTURES / scenario).glob("*.json")):
        files[path.name.removesuffix(".json")] = json.loads(path.read_text())
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mutation", required=True, choices=sorted(MUTATIONS))
    parser.add_argument("--out", help="Output scenario name (defaults to the mutation name)")
    arguments = parser.parse_args()

    base, _ = MUTATIONS[arguments.mutation]
    mutated = apply_mutation(load_scenario_files(base), arguments.mutation)

    out_dir = FIXTURES / (arguments.out or arguments.mutation)
    out_dir.mkdir(parents=True, exist_ok=True)
    for stem, fixture in mutated.items():
        (out_dir / f"{stem}.json").write_text(dump_fixture(fixture))
    print(f"Wrote fixtures/{out_dir.name} from {base} + {arguments.mutation}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
