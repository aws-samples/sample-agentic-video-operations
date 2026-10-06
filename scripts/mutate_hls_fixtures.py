"""Derive a broken HLS Doctor scenario from a recorded base fixture.

Usage:
    uv run python scripts/mutate_hls_fixtures.py --base hls_clean_vod \
        --mutation hls_broken_map [--out hls_broken_map]
"""

import argparse
import json
from pathlib import Path

from hls_fixture_mutations import MUTATIONS, apply_mutation, dump_fixture

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="Base scenario under fixtures/")
    parser.add_argument("--mutation", required=True, choices=sorted(MUTATIONS))
    parser.add_argument("--out", help="Output scenario name (defaults to the mutation name)")
    arguments = parser.parse_args()

    base_path = FIXTURES / arguments.base / "http.exchanges.json"
    fixture = json.loads(base_path.read_text())
    mutated = apply_mutation(fixture, arguments.mutation)

    out_dir = FIXTURES / (arguments.out or arguments.mutation)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "http.exchanges.json").write_text(dump_fixture(mutated))
    print(f"Wrote {out_dir / 'http.exchanges.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
