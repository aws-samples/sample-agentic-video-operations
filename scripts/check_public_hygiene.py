"""Refuse internal planning labels in files shipped by the repository."""

import re
import subprocess
import sys
from pathlib import Path

INTERNAL_LABEL = re.compile(
    r"(?<![A-Za-z0-9_])(?:[CG][0-9]+\.[0-9]+|R[0-9]+|"
    r"T[0-9]+[bB]?|RB[0-9]+|REN[0-9]+|"
    r"F[0-9]+(?:-B[0-9]+)?|PR[0-9]+-[0-9]+)(?![A-Za-z0-9_])"
)
BASE64_RUN = re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/=]{32,}(?![A-Za-z0-9+/=])")
LOCKFILE_INTEGRITY = re.compile(
    r'^\s*"integrity":\s*"sha(?:1|256|384|512)-[A-Za-z0-9+/=]+"\s*,?\s*$'
)
NOQA_DIRECTIVE = re.compile(r"#\s*noqa:\s*(?:[A-Z]+[0-9]+(?:,\s*)?)+")
ORDINARY_TERMS = re.compile(r"\b(?:Cloudflare R2|T3 instance|F1 score)\b")


def list_public_paths() -> list[Path]:
    """Return every tracked path, including published builder instructions."""
    result = subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=True)
    names = result.stdout.decode().split("\0")
    return [Path(name) for name in names if name]


def find_internal_labels(path: Path, text: str) -> list[str]:
    """Report internal labels with their public file and line."""
    problems: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if LOCKFILE_INTEGRITY.fullmatch(line):
            continue
        public_text = NOQA_DIRECTIVE.sub("", line)
        public_text = BASE64_RUN.sub("", public_text)
        public_text = ORDINARY_TERMS.sub("", public_text)
        for match in INTERNAL_LABEL.finditer(public_text):
            problems.append(f"{path}:{number}: internal plan label: {match.group(0)}")
    return problems


def read_text(path: Path) -> str | None:
    """Read a tracked text file, ignoring binary assets."""
    try:
        return path.read_text()
    except UnicodeDecodeError:
        return None


def main() -> int:
    problems = [
        problem
        for path in list_public_paths()
        if (text := read_text(path)) is not None
        for problem in find_internal_labels(path, text)
    ]
    for problem in problems:
        print(problem)
    print(
        "Public hygiene checks passed."
        if not problems
        else f"{len(problems)} public hygiene problem(s)."
    )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
