"""Scripts the READMEs run directly read the root .env, as `just` does (T61).

`just` loads the root .env (`set dotenv-load`), but the READMEs also show the raw
`uv run python scripts/...` command, and uv loads no .env. So a setting that is in .env
read as missing, and the message said to add it there.
"""

import ast
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import read_root_env

ROOT = Path(__file__).resolve().parents[2]
RAW_SCRIPT = re.compile(r"uv run python (scripts/[\w./-]+\.py)")
# A clean AWS environment: no credentials anywhere, so boto3 fails at once, offline.
NO_AWS = {
    "PATH": os.environ["PATH"],
    "HOME": "/nonexistent",
    "AWS_CONFIG_FILE": "/dev/null",
    "AWS_SHARED_CREDENTIALS_FILE": "/dev/null",
    "AWS_EC2_METADATA_DISABLED": "true",
}


def copy_scripts(tmp_path, env_text):
    shutil.copytree(ROOT / "scripts", tmp_path / "scripts", ignore=shutil.ignore_patterns("tests"))
    if env_text is not None:
        (tmp_path / ".env").write_text(env_text)
    return tmp_path / "scripts"


def run_script(scripts, *arguments):
    return subprocess.run(
        [sys.executable, str(scripts / arguments[0]), *arguments[1:]],
        capture_output=True, text=True, env=NO_AWS, cwd=scripts.parent, timeout=60,
    )  # fmt: skip


def test_invoke_agentic_iops_reads_aws_region_from_the_root_env(tmp_path):
    scripts = copy_scripts(tmp_path, "# settings\nAWS_REGION=us-west-2\n")

    result = run_script(
        scripts, "invoke_agentic_iops_streaming.py", "--actor", "alice", "List my channels"
    )

    assert "Missing AWS_REGION" not in result.stdout
    assert "The runtime call failed" in result.stdout  # it got as far as AWS, with no credentials


def test_a_missing_setting_names_the_file_that_was_read(tmp_path):
    scripts = copy_scripts(tmp_path, "AGENT_MODEL_ID=x\n")

    result = run_script(scripts, "invoke_agentic_iops_streaming.py", "--actor", "alice", "hi")

    assert f"Missing AWS_REGION: not set in the environment or in {tmp_path / '.env'}" in (
        result.stdout
    )


def test_a_missing_root_env_is_named_with_how_to_create_it(tmp_path):
    scripts = copy_scripts(tmp_path, None)

    result = run_script(scripts, "invoke_agentic_iops_streaming.py", "--actor", "alice", "hi")

    assert f"{tmp_path / '.env'} (not found: cp .env.example .env)" in result.stdout


def test_the_environment_wins_over_the_file_like_just(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "AWS_REGION=us-west-2\nexport MEMORY_ID='from-file'\nEMPTY=\n"
        'QUOTED="a # b"\nCOMMENTED=value # note\n# IGNORED=1\nnot a setting\n'
    )
    environ = {"AWS_REGION": "eu-west-1"}

    read_root_env.load_root_env(environ, path)

    assert environ == {
        "AWS_REGION": "eu-west-1",
        "MEMORY_ID": "from-file",
        "EMPTY": "",
        "QUOTED": "a # b",
        "COMMENTED": "value",
    }


def test_no_root_env_changes_nothing(tmp_path):
    environ = {"AWS_REGION": "eu-west-1"}
    read_root_env.load_root_env(environ, tmp_path / ".env")
    assert environ == {"AWS_REGION": "eu-west-1"}


def scripts_run_directly_by_docs():
    names = subprocess.run(
        ["git", "ls-files", "*.md"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    found = set()
    for name in names:
        if name.startswith(".claude/plans/") or name == "CHANGELOG.md":
            continue
        found.update(RAW_SCRIPT.findall((ROOT / name).read_text()))
    return sorted(found)


def reads_settings(tree):
    return any(
        isinstance(node, ast.Attribute) and node.attr == "environ" for node in ast.walk(tree)
    )


def loads_root_env_at_entry(tree):
    for node in tree.body:
        if isinstance(node, ast.If) and "__main__" in ast.unparse(node.test):
            return "load_root_env(os.environ)" in ast.unparse(node)
    return False


@pytest.mark.parametrize("script", scripts_run_directly_by_docs())
def test_every_script_a_doc_runs_directly_loads_the_root_env(script):
    tree = ast.parse((ROOT / script).read_text())
    if not reads_settings(tree):
        pytest.skip(f"{script} reads no settings")
    assert loads_root_env_at_entry(tree), f"{script} must call load_root_env(os.environ)"


def test_the_stack_scripts_name_the_file_when_a_setting_is_missing(capsys):
    import manage_agentic_iops_streaming_stack
    import manage_hydrolix_stack

    assert manage_agentic_iops_streaming_stack.read_deploy_settings({}) is None
    assert manage_hydrolix_stack.read_required_settings({}) is None

    output = capsys.readouterr().out
    expected = f"not set in the environment or in {read_root_env.describe_root_env()}"
    assert output.count(expected) == 2


def test_quotes_are_read_before_comments(tmp_path):
    """T61 review: a quoted value keeps its `#`, and a comment after it is dropped."""
    path = tmp_path / ".env"
    path.write_text(
        'export TOKEN="alpha=beta # literal" # operator note\n'
        "SINGLE='a # b'\t# note\n"
        "TABBED=value\t# note\n"
        "URL=https://example.com/a#fragment\n"
        "EQUALS=a=b=c # note\n"
        'UNCLOSED="half\n'
    )
    environ = {}

    read_root_env.load_root_env(environ, path)

    assert environ == {
        "TOKEN": "alpha=beta # literal",
        "SINGLE": "a # b",
        "TABBED": "value",
        "URL": "https://example.com/a#fragment",
        "EQUALS": "a=b=c",
        "UNCLOSED": '"half',
    }
