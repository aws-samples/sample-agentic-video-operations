"""`just clean` and `just clean-all` on a planted clone upgraded from an older release."""

import subprocess
from pathlib import Path

import clean_local_state as clean
import pytest

CDK = "samples/agentic-iops-streaming/cdk"
HYDROLIX_CDK = "samples/hydrolix/cdk-hydrolix-data-assistant-agentcore-strands"
WEB_APP = "samples/hydrolix/amplify-hydrolix-data-assistant-agentcore-strands"

TRACKED = (
    ".gitignore",
    f"{CDK}/cdk.json",
    f"{CDK}/bin/app.ts",
    f"{CDK}/lib/stack.ts",
    f"{CDK}/lib/handwritten.js",  # tracked JavaScript beside a .ts: never removed
    f"{CDK}/lib/handwritten.ts",
    f"{CDK}/jest.config.js",  # no .ts beside it: not a tsc output
    f"{HYDROLIX_CDK}/cdk.json",
    f"{HYDROLIX_CDK}/bin/app.ts",
    f"{WEB_APP}/src/main.ts",
    f"{WEB_APP}/src/main.js",
    "samples/medialive/README.md",
)
GENERATED = (
    "eval-results.json",  # the eval's old output path, before .cache/
    ".cache/eval-results.json",
    ".pytest_cache/v/x",
    "samples/medialive/src/__pycache__/m.cpython-313.pyc",
    f"{CDK}/cdk.out/manifest.json",
    f"{CDK}/bin/app.js",
    f"{CDK}/bin/app.d.ts",
    f"{CDK}/lib/stack.js",
    f"{CDK}/lib/stack.d.ts",
    f"{HYDROLIX_CDK}/cdk.out/tree.json",
    f"{HYDROLIX_CDK}/bin/app.js",
    f"{HYDROLIX_CDK}/bin/app.d.ts",
)
KEPT_UNLESS_ALL = (
    f"{CDK}/node_modules/aws-cdk-lib/index.js",
    f"{HYDROLIX_CDK}/node_modules/x/index.js",
    f"{WEB_APP}/node_modules/vite/index.js",
)
ALWAYS_KEPT = (
    ".env",
    f"{WEB_APP}/dist/index.js",  # the web app's own build: not a CDK app's tsc output
    ".venv/lib/python3.13/site-packages/p/__pycache__/p.pyc",
    f"{CDK}/node_modules/aws-cdk-lib/core.d.ts",
)
IGNORE = """.env
.cache/
.pytest_cache/
.venv/
__pycache__/
node_modules/
**/cdk.out/
/eval-results.json
samples/*/cdk/**/*.js
samples/*/cdk/**/*.d.ts
!samples/*/cdk/jest.config.js
dist/
"""


def plant(root: Path, paths: tuple[str, ...]) -> None:
    for path in paths:
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text("x")


@pytest.fixture
def clone(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)  # noqa: S607
    plant(tmp_path, TRACKED + GENERATED + KEPT_UNLESS_ALL + ALWAYS_KEPT)
    (tmp_path / ".gitignore").write_text(IGNORE)
    subprocess.run(  # noqa: S603
        ["git", "-C", str(tmp_path), "add", "-f", *TRACKED],  # noqa: S607
        check=True,
    )
    return tmp_path


def remaining(root: Path, paths: tuple[str, ...]) -> list[str]:
    return [path for path in paths if (root / path).exists()]


def test_clean_removes_generated_output_and_keeps_everything_else(clone, capsys):
    assert clean.main([], root=clone) == 0

    assert remaining(clone, GENERATED) == []
    assert remaining(clone, TRACKED) == list(TRACKED)
    assert remaining(clone, KEPT_UNLESS_ALL + ALWAYS_KEPT) == list(KEPT_UNLESS_ALL + ALWAYS_KEPT)
    printed = capsys.readouterr().out
    assert "removed eval-results.json" in printed
    assert f"removed {CDK}/cdk.out" in printed and f"removed {CDK}/bin/app.js" in printed


def test_clean_all_also_removes_node_modules(clone):
    assert clean.main(["--all"], root=clone) == 0

    assert remaining(clone, KEPT_UNLESS_ALL) == []
    assert remaining(clone, TRACKED) == list(TRACKED)
    assert (clone / ".env").exists() and (clone / ".venv").exists()


def test_a_dry_run_prints_the_same_paths_and_removes_nothing(clone, capsys):
    clean.main(["--all", "--dry-run"], root=clone)
    planned = capsys.readouterr().out

    assert remaining(clone, GENERATED + KEPT_UNLESS_ALL) == list(GENERATED + KEPT_UNLESS_ALL)
    clean.main(["--all"], root=clone)
    assert capsys.readouterr().out == planned.replace("would remove", "removed")


def test_the_web_apps_own_javascript_is_never_a_tsc_output(clone):
    clean.main([], root=clone)

    assert (clone / WEB_APP / "src/main.js").exists()


def test_a_leftover_pre_rename_hub_folder_with_only_ignored_content_is_removed(clone, capsys):
    plant(clone, ("samples/hub/cdk/node_modules/x/index.js", "samples/hub/cdk/cdk.out/m.json"))
    (clone / "samples/hub/src/hub").mkdir(parents=True)  # an empty skeleton

    clean.main([], root=clone)

    assert not (clone / "samples/hub").exists()
    assert "removed samples/hub (the sample's name before agentic-iops-streaming)" in (
        capsys.readouterr().out
    )


@pytest.mark.parametrize("kind", ["tracked", "untracked"])
def test_a_hub_folder_holding_real_files_is_kept_and_named(clone, capsys, kind):
    plant(clone, ("samples/hub/cdk/node_modules/x/index.js", "samples/hub/notes.md"))
    if kind == "tracked":
        subprocess.run(  # noqa: S603
            ["git", "-C", str(clone), "add", "samples/hub/notes.md"],  # noqa: S607
            check=True,
        )

    clean.main([], root=clone)

    assert (clone / "samples/hub/notes.md").exists()
    assert "kept samples/hub" in capsys.readouterr().out


def test_nothing_tracked_is_ever_removed_even_inside_a_target(clone):
    """A tracked file under cdk.out (someone force-added one) survives, and so does its folder."""
    plant(clone, (f"{CDK}/cdk.out/pinned.json",))
    subprocess.run(  # noqa: S603
        ["git", "-C", str(clone), "add", "-f", f"{CDK}/cdk.out/pinned.json"],  # noqa: S607
        check=True,
    )

    clean.main([], root=clone)

    assert (clone / CDK / "cdk.out/pinned.json").exists()
