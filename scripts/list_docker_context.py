"""List the files a `docker build` would send, using the same .dockerignore rules.

uv run python scripts/list_docker_context.py samples/agentic-iops-streaming/Dockerfile .

Rules, as in Docker: patterns are relative to the context root; `*` and `?` stay within one
path segment and `**` spans any number of segments; a path is excluded when it or a parent
directory matches; `!pattern` re-includes; the last matching pattern wins. A Dockerfile's
own `<Dockerfile>.dockerignore` replaces the context root's `.dockerignore`.
"""

import os
import re
import sys
from collections.abc import Iterator
from pathlib import Path


def read_ignore_patterns(dockerfile: Path, context: Path) -> list[str]:
    own = dockerfile.with_name(f"{dockerfile.name}.dockerignore")
    source = own if own.exists() else context / ".dockerignore"
    if not source.exists():
        return []
    lines = [line.strip() for line in source.read_text().splitlines()]
    return [line for line in lines if line and not line.startswith("#")]


def compile_pattern(pattern: str) -> re.Pattern[str]:
    text = pattern.strip("/")
    out, i = "", 0
    while i < len(text):
        if text.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif text.startswith("**", i):
            out, i = out + ".*", i + 2
        elif text[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif text[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(text[i]), i + 1
    return re.compile(f"^{out}$")


def is_excluded(path: str, rules: list[tuple[bool, re.Pattern[str]]]) -> bool:
    excluded = False
    for negated, pattern in rules:
        if matches_path_or_parent(path, [pattern]):
            excluded = not negated
    return excluded


def matches_path_or_parent(path: str, patterns: list[re.Pattern[str]]) -> bool:
    parts = path.split("/")
    candidates = ["/".join(parts[: n + 1]) for n in range(len(parts))]
    return any(pattern.match(candidate) for pattern in patterns for candidate in candidates)


def list_context(dockerfile: Path, context: Path) -> Iterator[str]:
    patterns = read_ignore_patterns(dockerfile, context)
    rules = [(p.startswith("!"), compile_pattern(p.removeprefix("!"))) for p in patterns]
    # A rule after the last `!` that matches a directory matches everything inside it (rules
    # match a path's parents too), and no later rule can re-include anything: prune the tree.
    last_negation = max((n for n, (negated, _) in enumerate(rules) if negated), default=-1)
    final_exclusions = [pattern for _, pattern in rules[last_negation + 1 :]]
    for root, directories, files in os.walk(context):
        relative = Path(root).relative_to(context).as_posix()
        prefix = "" if relative == "." else f"{relative}/"
        directories[:] = [
            d for d in directories if not matches_path_or_parent(prefix + d, final_exclusions)
        ]
        for name in files:
            path = prefix + name
            if not is_excluded(path, rules):
                yield path


FORBIDDEN = re.compile(
    r"(^|/)(\.env(?!\.example$)[^/]*|\.claude|\.git|cdk\.out|\.venv|node_modules|__pycache__"
    r"|\.cache|\.mypy_cache|\.ruff_cache|\.pytest_cache|\.hub-sessions|eval-results\.json)(/|$)"
)


def find_forbidden(paths: list[str]) -> list[str]:
    """Secrets, local state and tool caches that must never enter an image's build context."""
    return [path for path in paths if FORBIDDEN.search(path)]


def main(argv: list[str]) -> int:
    dockerfile, context = Path(argv[0]), Path(argv[1] if len(argv) > 1 else ".")
    paths = sorted(list_context(dockerfile, context))
    forbidden = find_forbidden(paths)
    for path in forbidden:
        print(f"in build context: {path}")
    print(f"{len(paths)} files in the context; {len(forbidden)} forbidden.")
    return 1 if forbidden else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
