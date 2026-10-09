"""Documentation declarations come only from files recorded by Git."""

import subprocess
from pathlib import Path

import check_docs_claims as claims


def write(root: Path, relative: str, text: str) -> None:
    """Write one test-repository file."""
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_claim_sources_ignore_untracked_local_files(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    write(
        tmp_path,
        "samples/tracked/pyproject.toml",
        '[project]\nname = "tracked-project"\n'
        '[project.scripts]\ntracked-command = "tracked:main"\n',
    )
    write(
        tmp_path,
        "samples/tracked/src/tracked/settings/runtime_settings.py",
        "class Settings(BaseSettings):\n    tracked_setting: str\n",
    )
    write(
        tmp_path,
        "samples/tracked/src/tracked/tool_surface.py",
        "@mcp.tool()\ndef describe_tracked():\n    pass\n",
    )
    write(
        tmp_path,
        "samples/tracked/cdk/stack.ts",
        "new cdk.CfnOutput(this, 'TrackedOutput', {});\n",
    )
    write(
        tmp_path,
        "scripts/tracked_cli.py",
        "import argparse\nparser = argparse.ArgumentParser()\nparser.add_argument('--tracked')\n",
    )
    subprocess.run(
        ["git", "add", "samples/tracked", "scripts/tracked_cli.py"], cwd=tmp_path, check=True
    )

    write(
        tmp_path,
        "samples/local/pyproject.toml",
        '[project]\nname = "local-project"\n[project.scripts]\nlocal-command = "local:main"\n',
    )
    write(
        tmp_path,
        "samples/local/src/local/settings/runtime_settings.py",
        "class Settings(BaseSettings):\n    local_setting: str\n",
    )
    write(
        tmp_path,
        "samples/local/src/local/tool_surface.py",
        "@mcp.tool()\ndef describe_local():\n    pass\n",
    )
    write(
        tmp_path,
        "samples/local/cdk/stack.ts",
        "new cdk.CfnOutput(this, 'LocalOutput', {});\n",
    )
    write(
        tmp_path,
        "scripts/local_cli.py",
        "import argparse\nparser = argparse.ArgumentParser()\nparser.add_argument('--local')\n",
    )
    write(tmp_path, ".env.example", "LOCAL_SETTING=\n")

    sources = claims.collect_claim_sources(tmp_path)

    assert sources.project_scripts == {"tracked-project": frozenset({"tracked-command"})}
    assert set(sources.script_interfaces) == {"scripts/tracked_cli.py"}
    assert "TRACKED_SETTING" in sources.settings
    assert "LOCAL_SETTING" not in sources.settings
    assert "describe_tracked" in sources.tools
    assert "describe_local" not in sources.tools
    assert sources.outputs == frozenset({"TrackedOutput"})
