"""`just docs-check`: the repository layout (guidelines §20, sample-contract §3).

Checks git-tracked paths only, so local artifacts (.venv, cdk.out) never fail it.
"""

import re
import subprocess
import sys
from collections.abc import Iterable

ALLOWED_ROOT = frozenset(
    {
        "README.md", "AGENTS.md", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md", "LICENSE",
        "justfile", "pyproject.toml", "uv.lock", ".env.example", ".python-version",
        ".gitignore", ".github", "docs", "samples", "packages", "fixtures", "scripts",
        ".claude",  # agent instructions and contracts; .claude/plans/ is never tracked
    }
)  # fmt: skip

# Today's folders and their destinations. Task R1 moves them and empties this mapping.
PENDING_MOVES = {
    "cmcd-mcp-server": "samples/cmcd",
    "mediaconnect-mcp-server": "samples/mediaconnect",
    "medialive-mcp-server": "samples/medialive",
    "media-services-langchain": "samples/hub",
    "hydrolix-cdn-insights": "samples/hydrolix",
    "media_ops_contracts": "packages/media_ops_contracts",
    "images": "docs/images",
}

IMAGE_EXTENSIONS = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".bmp", ".tif", ".tiff"}
)
DOCS_IMAGES = re.compile(r"^(docs/images/|samples/[^/]+/docs/images/)")


def find_layout_problems(tracked_paths: Iterable[str]) -> list[str]:
    paths = [path for path in tracked_paths if path.split("/", 1)[0] not in PENDING_MOVES]
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
    pending = ", ".join(f"{old} -> {new}" for old, new in PENDING_MOVES.items())
    if PENDING_MOVES:
        print(f"Pending moves (task R1): {pending}")
    print("Repository layout checks passed." if not problems else f"{len(problems)} problem(s).")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
