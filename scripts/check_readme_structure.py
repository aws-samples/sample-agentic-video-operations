"""`just docs-check`: README headings (guidelines §16) and relative links for converted samples,
and no internal task ids (C3.2, task G3.2, ...) in any user-facing document.

The repository layout is checked separately by check_repository_layout.py.

Add a sample's README to CONVERTED_READMES in the step that converts the sample.
"""

import re
import subprocess
import sys
from pathlib import Path

REQUIRED_HEADINGS = [
    "Purpose",
    "Architecture",
    "Prerequisites",
    "Setup and Run",
    "Teardown",
    "Known Limitations",
]
CONVERTED_READMES: list[str] = [
    "samples/cmcd/README.md",
    "samples/hydrolix/README.md",
    "samples/medialive/README.md",
]
LINK_PATTERN = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")
TASK_ID_PATTERN = re.compile(r"\b[Tt]ask [CGRT]\d+(?:\.\d+)?|\b[CG]\d+\.\d+")
USER_FACING_DOCS = ("*README.md", "AGENTS.md", "docs/*.md")


def find_task_ids(text: str) -> list[str]:
    """Internal plan ids mean nothing to a reader of the published sample."""
    return [
        f"internal task id on line {number}: {match.group(0)}"
        for number, line in enumerate(text.splitlines(), start=1)
        for match in TASK_ID_PATTERN.finditer(line)
    ]


def list_user_facing_docs() -> list[Path]:
    tracked = subprocess.run(
        ["git", "ls-files", *USER_FACING_DOCS], capture_output=True, text=True, check=True
    ).stdout.split()
    return [Path(path) for path in tracked if "node_modules" not in path]


def find_heading_problems(text: str) -> list[str]:
    headings = re.findall(r"^## (.+?)\s*$", text, flags=re.MULTILINE)
    missing = [heading for heading in REQUIRED_HEADINGS if heading not in headings]
    present = [heading for heading in headings if heading in REQUIRED_HEADINGS]
    expected_order = [heading for heading in REQUIRED_HEADINGS if heading in present]
    problems = [f"missing heading: ## {heading}" for heading in missing]
    if present != expected_order:
        problems.append(f"headings out of order: {present}")
    return problems


def find_broken_links(readme: Path, text: str) -> list[str]:
    targets = [target for target in LINK_PATTERN.findall(text) if "://" not in target]
    targets = [target for target in targets if not target.startswith("mailto:")]
    return [f"broken link: {target}" for target in targets if not (readme.parent / target).exists()]


def main() -> int:
    failures = 0
    for document in list_user_facing_docs():
        for problem in find_task_ids(document.read_text()):
            print(f"{document}: {problem}")
            failures += 1
    for name in CONVERTED_READMES:
        readme = Path(name)
        text = readme.read_text()
        problems = find_heading_problems(text) + find_broken_links(readme, text)
        for problem in problems:
            print(f"{readme}: {problem}")
        failures += len(problems)
    print("README checks passed." if not failures else f"{failures} README problem(s).")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
