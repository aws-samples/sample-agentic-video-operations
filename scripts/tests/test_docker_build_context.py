"""No image's build context holds a secret or local state (release gate)."""

import subprocess
from pathlib import Path

import list_docker_context as context
import pytest
from list_docker_builds import DOCKER_BUILDS

ROOT = Path(__file__).resolve().parents[2]
PLANTED = (
    ".env", ".env.local", "deep/dir/.env", "deep/.env.production", ".claude/plans/handoff.md",
    ".git/HEAD", "app/cdk.out/template.json",
)  # fmt: skip
BUILD_IDS = [build["dockerfile"] for build in DOCKER_BUILDS]


def test_every_tracked_dockerfile_is_built_in_ci():
    tracked = subprocess.run(
        ["git", "ls-files", "*Dockerfile"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    assert sorted(tracked) == sorted(BUILD_IDS)


@pytest.mark.parametrize("build", DOCKER_BUILDS, ids=BUILD_IDS)
def test_planted_secrets_and_local_state_stay_out_of_the_context(build, tmp_path):
    dockerfile = ROOT / build["dockerfile"]
    copy = tmp_path / Path(build["dockerfile"]).relative_to(build["context"])
    copy.parent.mkdir(parents=True, exist_ok=True)
    copy.write_text("FROM scratch")
    for ignore in (
        dockerfile.with_name(f"{dockerfile.name}.dockerignore"),
        ROOT / build["context"] / ".dockerignore",
    ):  # noqa: E501
        if ignore.exists():
            target = (
                copy.with_name(ignore.name)
                if ignore.name != ".dockerignore"
                else tmp_path / ".dockerignore"
            )  # noqa: E501
            target.write_text(ignore.read_text())
            break
    for path in (*PLANTED, ".env.example"):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text("x")

    paths = sorted(context.list_context(copy, tmp_path))

    assert context.find_forbidden(paths) == []
    assert ".env.example" in paths


@pytest.mark.parametrize("build", DOCKER_BUILDS, ids=BUILD_IDS)
def test_the_real_context_on_disk_has_nothing_forbidden(build):
    paths = sorted(context.list_context(ROOT / build["dockerfile"], ROOT / build["context"]))

    assert context.find_forbidden(paths) == []
    assert any(path.endswith("Dockerfile") for path in paths)


def test_the_matcher_follows_dockerignore_rules():
    rules = [
        (False, context.compile_pattern("**/.env*")),
        (True, context.compile_pattern("**/.env.example")),
    ]  # noqa: E501
    assert context.is_excluded(".env", rules)
    assert context.is_excluded("a/b/.env.local", rules)
    assert not context.is_excluded("a/.env.example", rules)
    assert context.is_excluded("cdk.out/x", [(False, context.compile_pattern("cdk.out"))])
    assert not context.is_excluded("a/cdk.out/x", [(False, context.compile_pattern("cdk.out"))])
