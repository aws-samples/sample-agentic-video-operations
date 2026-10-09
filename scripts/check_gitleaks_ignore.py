"""Require every gitleaks fingerprint to belong to published repository history."""

import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FINGERPRINT = re.compile(r"^(?P<commit>[0-9a-f]{40}):")
PUBLISHED_REF_PREFIXES = (
    "refs/remotes/origin/main",
    "refs/remotes/origin/release-candidate/",
)
CANONICAL_ORIGIN_PATH = "aws-samples/sample-agentic-video-operations"


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


def is_shallow_repository(root: Path = ROOT) -> bool:
    """Return whether Git reports that the clone has truncated history."""
    result = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip() == "true"


def read_origin_url(root: Path = ROOT) -> str:
    """Return the fetch URL used for the canonical published-history ref."""
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def local_test_skip_reason(*, shallow: bool, refs: list[str], origin_url: str) -> str | None:
    """Explain why a local clone cannot prove reachability against published history."""
    ci_note = "CI runs scripts/check_gitleaks_ignore.py against full canonical history."
    if shallow:
        return f"published-history check skipped in a shallow clone. {ci_note}"
    normalized_origin = origin_url.rstrip("/").removesuffix(".git")
    if not normalized_origin.endswith(CANONICAL_ORIGIN_PATH):
        return f"published-history check skipped in a fork or non-canonical clone. {ci_note}"
    if "refs/remotes/origin/main" not in refs:
        return f"published-history check skipped because origin/main is unavailable. {ci_note}"
    return None


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
    ancestor_check: Callable[[str, str], bool] = is_ancestor,
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
