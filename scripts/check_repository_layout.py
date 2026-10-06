"""`just docs-check`: the repository layout (guidelines §20, build_a_sample.md §3).

Checks git-tracked paths only, so local artifacts (.venv, cdk.out) never fail it.
"""

import re
import subprocess
import sys
from collections.abc import Iterable

ALLOWED_ROOT = frozenset(
    {
        "README.md", "AGENTS.md", "CHANGELOG.md", "CONTRIBUTING.md",
        "CODE_OF_CONDUCT.md", "LICENSE",
        "justfile", "pyproject.toml", "uv.lock", ".env.example", ".python-version",
        ".gitignore", ".gitleaksignore", ".pre-commit-config.yaml", ".github",
        "docs", "samples", "packages", "fixtures", "scripts",
        ".claude",  # Claude Code instructions; .claude/plans/ is never tracked
    }
)  # fmt: skip

IMAGE_EXTENSIONS = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".bmp", ".tif", ".tiff"}
)
DOCS_IMAGES = re.compile(r"^(docs/images/|samples/[^/]+/docs/images/)")


def find_layout_problems(tracked_paths: Iterable[str]) -> list[str]:
    paths = list(tracked_paths)
    web_apps = find_web_apps(paths)
    problems: set[str] = set()
    for path in paths:
        top = path.split("/", 1)[0]
        if top not in ALLOWED_ROOT:
            problems.add(f"root entry not allowed: {top}")
        if path.startswith(".claude/plans/"):
            problems.add(f"tracked plan file (keep .claude/plans/ local): {path}")
        if is_image(path) and not is_allowed_image(path, web_apps):
            problems.add(f"image outside docs/images/ or a web app: {path}")
    return sorted(problems)


def is_image(path: str) -> bool:
    name = path.rsplit("/", 1)[-1].lower()
    in_images_folder = "/images/" in f"/{path}"
    return in_images_folder or any(name.endswith(extension) for extension in IMAGE_EXTENSIONS)


def find_web_apps(paths: list[str]) -> set[str]:
    """Folders with a tracked package.json and a public/ folder (CDK apps have no public/)."""
    roots = {path.rsplit("/", 1)[0] for path in paths if path.endswith("/package.json")}
    return {root for root in roots if any(path.startswith(f"{root}/public/") for path in paths)}


def is_allowed_image(path: str, web_apps: set[str]) -> bool:
    if DOCS_IMAGES.match(path):
        return True
    return any(path.startswith((f"{app}/public/", f"{app}/src/")) for app in web_apps)


def list_tracked_paths() -> list[str]:
    result = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True)
    return result.stdout.splitlines()


def main() -> int:
    problems = find_layout_problems(list_tracked_paths())
    for problem in problems:
        print(problem)
    print("Repository layout checks passed." if not problems else f"{len(problems)} problem(s).")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
