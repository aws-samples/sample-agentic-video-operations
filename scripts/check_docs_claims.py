"""Release gate: every command, interface and path a published doc names exists.

uv run python scripts/check_docs_claims.py

Checks tracked published Markdown, including .claude/CLAUDE.md but not private .claude
process files or CHANGELOG.md (history may name removed things),
against the justfile, argparse declarations, project scripts, settings classes, tool
factories, and tracked repository paths. It also rejects plan wording as product state.
  The file or folder check: tracked by git. Untracked local files (node_modules,
  cdk.out) never satisfy a claim, so the check gives the same answer on every clone.
"""

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from validate_documented_commands import (
    ScriptInterface,
    find_command_problems,
    handled_arguments,
    read_project_scripts,
    read_recipes,
    read_script_interfaces,
)
from validate_documented_surfaces import (
    find_surface_problems,
    read_infrastructure_names,
    read_setting_names,
    read_tool_names,
)

ROOT = Path(__file__).resolve().parents[1]
REPO_PATH = re.compile(
    r"(?<![\w./-])((?:scripts|samples|docs|packages|fixtures)/[\w./<>*-]*[\w*>])"
)
SAMPLE_PATH = re.compile(
    r"(?<![\w./-])((?:src|tests|cdk|domain|entrypoints|settings|skills|tool_surface|workflows)"
    r"/[\w./<>*-]*[\w*>])"
)
RELATIVE_FILE = re.compile(
    r"(?<![\w./-])([A-Za-z_<>*-][\w<>*-]*(?:/[\w.<>*-]+)*"
    r"\.(?:json|md|py|sh|toml|ts|tsx|yaml|yml))"
)
CODE = re.compile(r"`([^`\n]+)`|```[^\n]*\n(.*?)```", re.DOTALL)
LINK = re.compile(r"\]\(([^)\s]+)")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)
# Plan language presented as product state.
FUTURE_STATE = re.compile(
    r"\b(has not landed|not landed yet|not implemented|not yet|comes later|"
    r"will be added|is coming soon|is planned|"
    r"being added|when[^.\n]{0,60}\blands|"
    r"(?:will|arrives?|available|lands?|planned|deferred)[^.\n]{0,30}\blater|"
    r"future (?:runtime|release|task|step|work|change|version|implementation|feature)|"
    r"(?:is|are|remains?|has|have|does|do|can|cannot|can't)[^.\n]{0,40}\byet|"
    r"(after|until|before) step \d+[a-z]?|step \d+[a-z]? lands)\b"
    r"|(?:^|\s)TODO\s*:"
    r"|(?:^|,\s+)(?!or\b)[a-z][\w-]*(?:\s+(?:support|sample|runtime|feature|"
    r"integration|deployment|coverage))?\s+later\b",
    re.IGNORECASE,
)
CONDITIONAL_NOT_YET = re.compile(
    r"\b(?:if|when)\b[^.\n]{0,80}\b(?:is|are|was|were|has|have)\s+not yet\s+"
    r"(?:been\s+)?[a-z][a-z-]*(?:ed|en)\b",
    re.IGNORECASE,
)
handled_samples = handled_arguments


@dataclass(frozen=True)
class ClaimSources:
    """Repository declarations against which published claims are checked."""

    tracked: frozenset[str]
    project_scripts: dict[str, frozenset[str]]
    script_interfaces: dict[str, ScriptInterface]
    settings: frozenset[str]
    tools: frozenset[str]
    outputs: frozenset[str]
    parameters: frozenset[str]


def collect_claim_sources(root: Path) -> ClaimSources:
    outputs, parameters = read_infrastructure_names(root)
    return ClaimSources(
        tracked=tracked_paths(root),
        project_scripts=read_project_scripts(root),
        script_interfaces=read_script_interfaces(root),
        settings=read_setting_names(root),
        tools=read_tool_names(root),
        outputs=outputs,
        parameters=parameters,
    )


def find_problems(
    doc: Path,
    text: str,
    recipes: dict[str, str],
    sources: ClaimSources | None = None,
) -> list[str]:
    sources = sources or collect_claim_sources(ROOT)
    problems = []
    spans = [m.group(1) or m.group(2) for m in CODE.finditer(text)]
    problems.extend(
        find_command_problems(
            doc,
            spans,
            recipes,
            sources.project_scripts,
            sources.script_interfaces,
        )
    )
    problems.extend(
        find_surface_problems(
            doc,
            text,
            sources.settings,
            sources.tools,
            sources.outputs,
            sources.parameters,
        )
    )
    for span in spans:
        checked_paths = set()
        for path in REPO_PATH.findall(span):
            checked_paths.add(path)
            if not is_tracked_claim(path.rstrip("/"), sources.tracked):
                problems.append(f"{doc}: {path} does not exist")
        if sample_root := sample_root_for(doc):
            for path in SAMPLE_PATH.findall(span):
                checked_paths.add(path)
                claimed = f"{sample_root}/{path.rstrip('/')}"
                if not is_tracked_claim(claimed, sources.tracked):
                    problems.append(f"{doc}: {path} does not exist under {sample_root}")
            for path in RELATIVE_FILE.findall(span):
                if path in checked_paths or "/" in path:
                    continue
                if not sample_file_exists(path, sample_root, sources.tracked):
                    problems.append(f"{doc}: {path} does not exist under {sample_root}")
        if doc.parts and doc.parts[0] == "docs":
            for path in RELATIVE_FILE.findall(span):
                if path in checked_paths or "/" not in path:
                    continue
                if is_package_relative(path, sources.tracked) and not package_path_exists(
                    path, sources.tracked
                ):
                    problems.append(f"{doc}: package path {path} does not exist")
    if doc != Path("docs/follow_development_guidelines.md"):
        problems.extend(find_future_state_problems(doc, text))
    for target in LINK.findall(text):
        if target.startswith(("http", "mailto:")):
            continue
        path, _, fragment = target.partition("#")
        resolved = (ROOT / doc.parent / (path or doc.name)).resolve()
        if not resolved.is_relative_to(ROOT) or not is_tracked(
            resolved.relative_to(ROOT).as_posix(), sources.tracked
        ):
            problems.append(f"{doc}: link {target} does not exist")
        elif fragment and fragment not in markdown_anchors(resolved):
            problems.append(f"{doc}: link anchor {target} does not exist")
    return problems


def find_future_state_problems(doc: Path, text: str) -> list[str]:
    problems = []
    for number, line in enumerate(text.splitlines(), start=1):
        conditionals = list(CONDITIONAL_NOT_YET.finditer(line))
        match = next(
            (
                candidate
                for candidate in FUTURE_STATE.finditer(line)
                if not any(
                    conditional.start() <= candidate.start()
                    and candidate.end() <= conditional.end()
                    for conditional in conditionals
                )
            ),
            None,
        )
        if match:
            problems.append(f"{doc}:{number}: plan language as product state: {match.group(0)!r}")
    return problems


def find_justfile_problems(text: str) -> list[str]:
    """Reject planning language in user-facing justfile messages and comments."""
    return find_future_state_problems(Path("justfile"), text)


def tracked_paths(root: Path = ROOT) -> frozenset[str]:
    """Tracked files and their parent folders: local, untracked files never satisfy a claim."""
    files = subprocess.run(
        ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.split()  # noqa: E501
    folders = {"/".join(f.split("/")[:n]) for f in files for n in range(1, f.count("/") + 1)}
    return frozenset(files) | frozenset(folders)


def is_tracked(path: str, tracked: frozenset[str]) -> bool:
    return path in tracked or path == "."


def is_tracked_claim(path: str, tracked: frozenset[str]) -> bool:
    if not any(marker in path for marker in ("<", ">", "*")):
        return is_tracked(path, tracked)
    pattern = "".join(
        "[^/]+" if piece.startswith("<") else "[^/]*" if piece == "*" else re.escape(piece)
        for piece in re.split(r"(<[^>]+>|\*)", path)
        if piece
    )
    return any(re.fullmatch(pattern, candidate) for candidate in tracked)


def sample_file_exists(path: str, sample_root: str, tracked: frozenset[str]) -> bool:
    prefix = f"{sample_root}/"
    return (
        is_tracked(path, tracked)
        or is_tracked(f"{sample_root}/{path}", tracked)
        or any(
            candidate.startswith(prefix) and candidate.endswith(f"/{path}") for candidate in tracked
        )
    )


def is_package_relative(path: str, tracked: frozenset[str]) -> bool:
    package = path.split("/", 1)[0]
    return any(candidate.endswith(f"/src/{package}") for candidate in tracked)


def package_path_exists(path: str, tracked: frozenset[str]) -> bool:
    package = path.split("/", 1)[0]
    return any(
        is_tracked(f"{candidate}/{path.removeprefix(f'{package}/')}", tracked)
        for candidate in tracked
        if candidate.endswith(f"/src/{package}")
    )


def markdown_anchors(path: Path) -> frozenset[str]:
    """Return GitHub-style heading anchors for one Markdown file."""
    if not path.is_file() or path.suffix.lower() != ".md":
        return frozenset()
    counts: dict[str, int] = {}
    anchors = set()
    for heading in HEADING.findall(path.read_text()):
        slug = re.sub(r"[^\w\s-]", "", re.sub(r"`([^`]*)`", r"\1", heading).lower())
        slug = re.sub(r"\s", "-", slug).strip("-")
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        anchors.add(slug if count == 0 else f"{slug}-{count}")
    return frozenset(anchors)


def sample_root_for(doc: Path) -> str | None:
    parts = doc.parts
    return "/".join(parts[:2]) if len(parts) >= 2 and parts[0] == "samples" else None


def tracked_docs() -> list[Path]:
    names = subprocess.run(
        ["git", "ls-files", "*.md"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()  # noqa: E501
    return [
        ROOT / name for name in names
        if (
            (not name.startswith(".claude/") or name == ".claude/CLAUDE.md")
            and name != "CHANGELOG.md"
            and "node_modules" not in name
        )
    ]  # fmt: skip


def main() -> int:
    justfile = (ROOT / "justfile").read_text()
    recipes = read_recipes(justfile)
    sources = collect_claim_sources(ROOT)
    problems = [
        p
        for doc in tracked_docs()
        for p in find_problems(
            doc.relative_to(ROOT),
            doc.read_text(),
            recipes,
            sources,
        )
    ]  # noqa: E501
    problems.extend(find_justfile_problems(justfile))
    for problem in problems:
        print(problem)
    print("Doc claims checks passed." if not problems else f"{len(problems)} doc claim problem(s).")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
