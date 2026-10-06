"""Require every gitleaks fingerprint to belong to published repository history."""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FINGERPRINT = re.compile(r"^(?P<commit>[0-9a-f]{40}):")
PUBLISHED_REF_PREFIXES = (
    "refs/remotes/origin/main",
    "refs/remotes/origin/release-candidate/",
)


def read_ignored_commits(path: Path) -> list[str]:
    """Return commit ids from non-comment gitleaks fingerprints."""
    commits = []
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line or line.startswith("#"):
            continue
        match = FINGERPRINT.match(line)
        if match is None:
            raise ValueError(f"{path}:{number}: expected a full commit fingerprint")
        commits.append(match.group("commit"))
    return commits


def list_published_refs(root: Path = ROOT) -> list[str]:
    """List canonical GitHub main and release-candidate remote refs."""
    result = subprocess.run(
        ["git", "for-each-ref", "--format=%(refname)", *PUBLISHED_REF_PREFIXES],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return [ref for ref in result.stdout.splitlines() if ref]


def is_ancestor(commit: str, ref: str, root: Path = ROOT) -> bool:
    """Return whether a commit is reachable from one published ref."""
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, ref],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def find_unreachable_commits(
    commits: list[str],
    refs: list[str],
    ancestor_check=is_ancestor,
) -> list[str]:
    """Return ignore commits that no published ref can reach."""
    return [commit for commit in commits if not any(ancestor_check(commit, ref) for ref in refs)]


def main() -> int:
    refs = list_published_refs()
    if "refs/remotes/origin/main" not in refs:
        print("origin/main is unavailable; fetch full published history before this check.")
        return 1
    try:
        commits = read_ignored_commits(ROOT / ".gitleaksignore")
    except ValueError as error:
        print(error)
        return 1
    unreachable = find_unreachable_commits(commits, refs)
    for commit in unreachable:
        print(f".gitleaksignore commit {commit} is not reachable from a published ref.")
    print(
        "Gitleaks ignore history check passed."
        if not unreachable
        else f"{len(unreachable)} unreachable gitleaks ignore commit(s)."
    )
    return 1 if unreachable else 0


if __name__ == "__main__":
    sys.exit(main())
