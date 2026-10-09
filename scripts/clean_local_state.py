"""Remove what local runs leave behind, and what an older release left (`just clean`).

uv run python scripts/clean_local_state.py [--all] [--dry-run]

Every target comes from a fixed pattern below, and nothing git tracks is ever removed: a
folder holding a tracked file is kept and named. `.git`, `.venv` and `node_modules` are never
walked into, so a package's own files are never mistaken for ours.

- Tool caches at the root, and every `__pycache__`.
- `eval-results.json` at the root: the eval wrote it there before it moved under `.cache/`.
- Every `cdk.out/`, and `tsc` output beside the sources of a CDK app (a folder with
  `cdk.json`): `X.js` and `X.d.ts` next to `X.ts`. The web app has no `cdk.json`, so its own
  JavaScript is never touched.
- `samples/hub/`, the sample's name before agentic-iops-streaming, when it holds nothing
  tracked and nothing unignored: an upgraded clone keeps its node_modules and cdk.out there.
- With `--all` (`just clean-all`), every `node_modules/` too.
"""

import argparse
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHES = (".cache", ".mypy_cache", ".ruff_cache", ".pytest_cache")
LEGACY_FILES = ("eval-results.json",)
NEVER_WALKED = frozenset({".git", ".venv", "node_modules"})
GENERATED_FOLDERS = frozenset({"__pycache__", "cdk.out"})
OLD_HUB = "samples/hub"
OLD_HUB_NOTE = "the sample's name before agentic-iops-streaming"


@dataclass
class Plan:
    remove: list[str] = field(default_factory=list)  # relative paths, files and folders
    notes: dict[str, str] = field(default_factory=dict)  # a removed path's explanation
    kept: list[str] = field(default_factory=list)  # what a pattern matched but must stay


def git_paths(root: Path, *arguments: str) -> list[str]:
    result = subprocess.run(  # noqa: S603 - fixed git arguments
        ["git", "-C", str(root), "ls-files", "-z", *arguments],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    )
    return [path for path in result.stdout.split("\0") if path]


def holds_tracked(path: str, tracked: frozenset[str]) -> bool:
    return path in tracked or any(name.startswith(f"{path}/") for name in tracked)


def plan_clean(root: Path, *, node_modules: bool) -> Plan:
    tracked = frozenset(git_paths(root))
    plan = Plan()

    def target(path: str, note: str = "") -> None:
        if holds_tracked(path, tracked):
            plan.kept.append(f"kept {path}: it holds files git tracks")
        elif (root / path).exists() or (root / path).is_symlink():
            plan.remove.append(path)
            if note:
                plan.notes[path] = note

    for name in (*CACHES, *LEGACY_FILES):
        target(name)
    walk_skips = plan_old_hub(root, plan, tracked)
    cdk_apps: list[str] = []
    for directory, folders, files in os.walk(root):
        relative = Path(directory).relative_to(root).as_posix()
        prefix = "" if relative == "." else f"{relative}/"
        if "cdk.json" in files:
            cdk_apps.append(prefix)
        kept_folders = []
        for name in sorted(folders):
            path = prefix + name
            if path in walk_skips or (not prefix and name in CACHES):
                continue
            if name in GENERATED_FOLDERS or (name == "node_modules" and node_modules):
                target(path)
            elif name not in NEVER_WALKED:
                kept_folders.append(name)
        folders[:] = kept_folders
        if any(prefix.startswith(app) for app in cdk_apps):
            for name in sorted(files):
                if name.endswith(".ts") and not name.endswith(".d.ts"):
                    stem = prefix + name.removesuffix(".ts")
                    for output in (f"{stem}.js", f"{stem}.d.ts"):
                        if (root / output).is_file():
                            target(output)
    return plan


def plan_old_hub(root: Path, plan: Plan, tracked: frozenset[str]) -> set[str]:
    """Plan `samples/hub/` as one removal when only ignored leftovers remain there."""
    if not (root / OLD_HUB).is_dir():
        return set()
    unignored = git_paths(root, "--others", "--exclude-standard", "--", OLD_HUB)
    if holds_tracked(OLD_HUB, tracked) or unignored:
        plan.kept.append(
            f"kept {OLD_HUB} ({OLD_HUB_NOTE}): it holds files that are tracked or not "
            "ignored; move what you need, then delete it yourself"
        )
        return set()
    plan.remove.append(OLD_HUB)
    plan.notes[OLD_HUB] = OLD_HUB_NOTE
    return {OLD_HUB}


def remove(root: Path, relative: str) -> None:
    path = root / relative
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def main(argv: Sequence[str], root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--all", action="store_true", help="also remove every node_modules/")
    parser.add_argument("--dry-run", action="store_true", help="print, remove nothing")
    arguments = parser.parse_args(argv)
    try:
        plan = plan_clean(root, node_modules=arguments.all)
    except (OSError, subprocess.CalledProcessError):
        print("Nothing was removed: git could not list the tracked files, so none is safe.")
        return 1
    verb = "would remove" if arguments.dry_run else "removed"
    for relative in sorted(plan.remove):
        if not arguments.dry_run:
            remove(root, relative)
        note = f" ({plan.notes[relative]})" if relative in plan.notes else ""
        print(f"{verb} {relative}{note}")
    for line in plan.kept:
        print(line)
    if not plan.remove:
        print("Nothing to remove.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
