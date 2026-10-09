"""Signal-map tags are supplied only when the map is created."""

import ast
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_OPERATION_NAMES = frozenset({"create_tags", "CreateTags"})


def find_create_tags_references(source: str) -> list[int]:
    """Return lines that directly name the forbidden standalone tag operation."""
    tree = ast.parse(source)
    lines = {
        node.lineno
        for node in ast.walk(tree)
        if (
            isinstance(node, ast.Attribute)
            and node.attr in FORBIDDEN_OPERATION_NAMES
            or isinstance(node, ast.Constant)
            and node.value in FORBIDDEN_OPERATION_NAMES
        )
    }
    return sorted(lines)


def tracked_sample_source_paths() -> list[Path]:
    """Return every tracked Python file below a sample's source root."""
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", "samples"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    paths = result.stdout.decode().split("\0")
    return [
        ROOT / path
        for path in paths
        if path.endswith(".py") and len(Path(path).parts) > 3 and Path(path).parts[2] == "src"
    ]


def test_a_direct_create_tags_call_is_detected():
    source = "def tag(client):\n    client.create_tags(ResourceArn='arn', Tags={})\n"
    assert find_create_tags_references(source) == [2]


def test_a_call_aws_operation_create_tags_call_is_detected():
    source = 'call_aws_operation(client, "create_tags", ResourceArn="arn", Tags={})\n'
    assert find_create_tags_references(source) == [1]


def test_a_getattr_create_tags_call_is_detected():
    source = 'getattr(client, "create_tags")(ResourceArn="arn", Tags={})\n'
    assert find_create_tags_references(source) == [1]


def test_a_pascal_case_or_held_operation_name_is_detected():
    source = 'operation = "CreateTags"\ncall_aws_operation(client, operation)\n'
    assert find_create_tags_references(source) == [1]


def test_create_signal_map_with_tags_is_allowed():
    source = "client.create_signal_map(Name='map', Tags={'managed-by': 'sample'})\n"
    assert find_create_tags_references(source) == []


def test_tracked_source_discovery_is_repository_rooted(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    paths = tracked_sample_source_paths()

    assert paths
    assert all(path.is_relative_to(ROOT / "samples") for path in paths)
    assert all(path.relative_to(ROOT).parts[2] == "src" for path in paths)


def test_no_sample_source_references_create_tags():
    problems = [
        f"{path.relative_to(ROOT)}:{line}"
        for path in tracked_sample_source_paths()
        for line in find_create_tags_references(path.read_text())
    ]
    assert problems == [], "standalone CreateTags references: " + ", ".join(problems)
