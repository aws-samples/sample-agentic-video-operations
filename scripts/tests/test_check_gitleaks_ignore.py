import check_gitleaks_ignore as check
import pytest


def test_every_gitleaks_ignore_commit_is_reachable_from_published_history():
    commits = check.read_ignored_commits(check.ROOT / ".gitleaksignore")
    refs = check.list_published_refs()

    assert check.find_unreachable_commits(commits, refs) == []


def test_an_ignore_for_an_unpublished_commit_fails():
    def published_only(commit, ref):
        return commit == "a" * 40 and ref == "refs/remotes/origin/main"

    assert check.find_unreachable_commits(
        ["a" * 40, "b" * 40],
        ["refs/remotes/origin/main", "refs/remotes/origin/release-candidate/rc"],
        published_only,
    ) == ["b" * 40]


def test_ignore_entries_require_a_full_commit_id(tmp_path):
    ignore = tmp_path / ".gitleaksignore"
    ignore.write_text("937d69b:path:rule:1\n")

    with pytest.raises(ValueError, match="expected a full commit fingerprint"):
        check.read_ignored_commits(ignore)
