"""`just docs-check`: README headings (guidelines §16) and relative links for converted samples.

Add a sample's README to CONVERTED_READMES in the step that converts the sample.
"""

import re
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
CONVERTED_READMES: list[str] = ["cmcd-mcp-server/README.md"]
LINK_PATTERN = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")


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
    if not CONVERTED_READMES:
        print("No converted samples yet.")
        return 0
    failures = 0
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
