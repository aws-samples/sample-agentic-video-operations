"""Fail when a tracked file mentions a Bedrock model ID that is not canonical.

Model IDs rot quietly: a doc keeps recommending a retired snapshot, or one
sample upgrades while another keeps the old default. This check scans every
tracked text file for Anthropic/Nova model-ID literals and compares them with
the allowlist in `model_ids.py`, so an upgrade is a one-file change plus a
mechanical sweep of whatever this script reports.
"""

import re
import subprocess
import sys
from pathlib import Path

from model_ids import ALLOWED_MODEL_IDS

REPO_ROOT = Path(__file__).resolve().parent.parent

MODEL_ID_PATTERN = re.compile(
    r"\b(?:us\.|eu\.|apac\.|global\.)?(?:anthropic\.claude|amazon\.nova)-[a-z0-9.:-]*[a-z0-9]"
)

# Files allowed to mention non-canonical IDs: the allowlist, this check and its
# tests, and the price table, which is keyed by base-model prefixes on purpose.
EXEMPT_FILES = {
    "scripts/model_ids.py",
    "scripts/check_model_ids.py",
    "scripts/tests/test_check_model_ids.py",
    "packages/media_ops_contracts/src/media_ops_contracts/estimate_model_cost.py",
    "packages/media_ops_contracts/tests/unit/test_estimate_model_cost.py",
}


def tracked_files() -> list[str]:
    output = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return output.splitlines()


def find_unknown_model_ids() -> list[str]:
    problems: list[str] = []
    for relative_path in tracked_files():
        if relative_path in EXEMPT_FILES:
            continue
        path = REPO_ROOT / relative_path
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for match in MODEL_ID_PATTERN.finditer(line):
                if match.group(0) not in ALLOWED_MODEL_IDS:
                    problems.append(
                        f"{relative_path}:{line_number}: unknown model ID {match.group(0)!r}"
                    )
    return problems


def main() -> int:
    problems = find_unknown_model_ids()
    if problems:
        print("Model IDs outside scripts/model_ids.py allowlist:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print(
            "Add the ID to scripts/model_ids.py (verified, dated) or fix the reference.",
            file=sys.stderr,
        )
        return 1
    print("Model ID checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
