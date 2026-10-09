import check_gitleaks_ignore as check
import pytest


def test_every_gitleaks_ignore_commit_is_reachable_from_published_history():
    commits = check.read_ignored_commits(check.ROOT / ".gitleaksignore")
    refs = check.list_published_refs()
    if reason := check.local_test_skip_reason(
        shallow=check.is_shallow_repository(),
        refs=refs,
        origin_url=check.read_origin_url(),
    ):
        pytest.skip(reason)

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


@pytest.mark.parametrize(
    ("shallow", "refs", "origin_url", "reason"),
    [
        (
            True,
            ["refs/remotes/origin/main"],
            "git@github.com:aws-samples/sample-agentic-video-operations.git",
            "shallow clone",
        ),
        (
            False,
            ["refs/remotes/origin/main"],
            "git@github.com:someone/sample-agentic-video-operations.git",
            "fork or non-canonical clone",
        ),
        (
            False,
            [],
            "git@github.com:aws-samples/sample-agentic-video-operations.git",
            "origin/main is unavailable",
        ),
    ],
)
def test_local_history_limits_have_a_clear_skip_reason(shallow, refs, origin_url, reason):
    message = check.local_test_skip_reason(
        shallow=shallow,
        refs=refs,
        origin_url=origin_url,
    )
    assert message is not None and reason in message and "CI runs" in message


def test_complete_canonical_history_does_not_skip():
    for origin_url in (
        "https://github.com/aws-samples/sample-agentic-video-operations",
        "git@github.com:aws-samples/sample-agentic-video-operations.git",
    ):
        assert (
            check.local_test_skip_reason(
                shallow=False,
                refs=["refs/remotes/origin/main"],
                origin_url=origin_url,
            )
            is None
        )
