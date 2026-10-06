"""Generated files stay out of the repository and out of the repository root."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read_gitignore() -> set[str]:
    lines = (ROOT / ".gitignore").read_text().splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


def test_gitignore_lists_every_generated_directory_itself():
    # Tools drop their own `*` .gitignore into their caches; the repository must not rely on it.
    required = {
        ".cache/",
        ".venv/",
        ".mypy_cache/",
        ".ruff_cache/",
        ".pytest_cache/",
        "__pycache__/",
        "node_modules/",
        "**/cdk.out/",
        ".DS_Store",
        ".env",
    }
    assert required <= read_gitignore()


def test_tool_caches_live_under_one_cache_directory():
    settings = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]
    assert settings["ruff"]["cache-dir"] == ".cache/ruff"
    assert settings["mypy"]["cache_dir"] == ".cache/mypy"
    assert settings["pytest"]["ini_options"]["cache_dir"] == ".cache/pytest"
