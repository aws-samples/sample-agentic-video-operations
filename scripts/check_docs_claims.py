"""Release gate: every command and repository path a published doc names exists.

uv run python scripts/check_docs_claims.py

Checks tracked Markdown outside .claude/ and CHANGELOG.md (history may name removed things):
- `just <recipe> [sample]`: the recipe exists, and a sample argument is handled by the
  recipe instead of falling through to "not converted yet" or "unknown sample";
- repository paths in code spans or links (scripts/, samples/, docs/, packages/,
  fixtures/): the file or folder is tracked by git;
- no plan language presented as product state ("has not landed", "after step 4").
  The file or folder check: tracked by git. Untracked local files (node_modules,
  cdk.out) never satisfy a claim, so the check gives the same answer on every clone.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JUST_COMMAND = re.compile(r"\bjust ([a-z][a-z-]*)(?: ([a-z][a-z0-9-]*))?")
REPO_PATH = re.compile(r"(?<![\w./-])((?:scripts|samples|docs|packages|fixtures)/[\w./<>*-]*[\w*])")
CODE = re.compile(r"`([^`\n]+)`|```[^\n]*\n(.*?)```", re.DOTALL)
LINK = re.compile(r"\]\(([^)#\s]+)")
# Plan language presented as product state: "has not landed", "after step 4", "until step 4c".
FUTURE_STATE = re.compile(
    r"\b(has not landed|not landed yet|(after|until|before) step \d+[a-z]?|step \d+[a-z]? lands)\b",
    re.IGNORECASE,
)
SAMPLE_RECIPES = ("run", "test", "deploy", "destroy")


def read_recipes(justfile: str) -> dict[str, str]:
    """Recipe name -> its body text."""
    recipes, current = {}, None
    for line in justfile.splitlines():
        header = re.match(r"^([a-z_][a-z0-9_-]*)(?: [^:]*)?:(?!=)", line)
        if header and not line.startswith(" "):
            current = header.group(1)
            recipes[current] = ""
        elif current and line.startswith(" "):
            recipes[current] += line + "\n"
    return recipes


def handled_samples(body: str) -> set[str]:
    """Sample keys a recipe's case statement routes to a real command."""
    handled = set()
    for keys, action in re.findall(r"^\s*([a-z|]+)\)\s*(.*?);;", body, re.MULTILINE):
        if "_pending" not in action and "_unknown" not in action and "exit 1" not in action:
            handled |= set(keys.split("|"))
    return handled


def find_problems(
    doc: Path, text: str, recipes: dict[str, str], tracked: frozenset[str] | None = None
) -> list[str]:
    tracked = tracked if tracked is not None else tracked_paths()
    problems = []
    spans = [m.group(1) or m.group(2) for m in CODE.finditer(text)]
    for span in spans:
        for recipe, argument in JUST_COMMAND.findall(span):
            if recipe not in recipes:
                problems.append(f"{doc}: `just {recipe}` is not a recipe")
            elif re.fullmatch(r"\s*@?just _pending\S*[^\n]*\n?", recipes[recipe]):
                problems.append(f"{doc}: `just {recipe}` is only a placeholder")
            elif (
                recipe in SAMPLE_RECIPES
                and argument
                and argument not in handled_samples(recipes[recipe])
            ):  # noqa: E501
                problems.append(f"{doc}: `just {recipe} {argument}` is not implemented")
        for path in REPO_PATH.findall(span):
            if not is_template(path) and not is_tracked(path.rstrip("/"), tracked):
                problems.append(f"{doc}: {path} does not exist")
    for number, line in enumerate(text.splitlines(), start=1):
        if match := FUTURE_STATE.search(line):
            problems.append(f"{doc}:{number}: plan language as product state: {match.group(0)!r}")
    for target in LINK.findall(text):
        if target.startswith(("http", "mailto:")):
            continue
        resolved = (ROOT / doc.parent / target).resolve()
        if not resolved.is_relative_to(ROOT) or not is_tracked(
            resolved.relative_to(ROOT).as_posix(), tracked
        ):
            problems.append(f"{doc}: link {target} does not exist")
    return problems


def tracked_paths() -> frozenset[str]:
    """Tracked files and their parent folders: local, untracked files never satisfy a claim."""
    files = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()  # noqa: E501
    folders = {"/".join(f.split("/")[:n]) for f in files for n in range(1, f.count("/") + 1)}
    return frozenset(files) | frozenset(folders)


def is_tracked(path: str, tracked: frozenset[str]) -> bool:
    return path in tracked or path == "."


def is_template(path: str) -> bool:
    return any(marker in path for marker in ("<", ">", "*"))


def tracked_docs() -> list[Path]:
    names = subprocess.run(
        ["git", "ls-files", "*.md"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()  # noqa: E501
    return [
        ROOT / name for name in names
        if not name.startswith(".claude/") and name != "CHANGELOG.md" and "node_modules" not in name
    ]  # fmt: skip


def main() -> int:
    recipes = read_recipes((ROOT / "justfile").read_text())
    problems = [
        p
        for doc in tracked_docs()
        for p in find_problems(doc.relative_to(ROOT), doc.read_text(), recipes)
    ]  # noqa: E501
    for problem in problems:
        print(problem)
    print("Doc claims checks passed." if not problems else f"{len(problems)} doc claim problem(s).")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
