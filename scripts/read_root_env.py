"""Scripts read the root .env the way `just` does, so their raw commands work too.

`just` loads the root .env itself (`set dotenv-load`), but the READMEs also show each
recipe's raw `uv run python scripts/...` command, and uv loads no .env. A script that reads
settings calls `load_root_env(os.environ)` at entry: values from the file fill only what
the environment doesn't set (the environment wins, as with just), and child processes such
as the AWS CLI and CDK see the same settings as under just.
"""

import re
from collections.abc import MutableMapping
from pathlib import Path

ROOT_ENV = Path(__file__).resolve().parents[1] / ".env"
COMMENT = re.compile(r"[ \t]#")


def load_root_env(environ: MutableMapping[str, str], path: Path = ROOT_ENV) -> None:
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        name, separator, value = line.strip().removeprefix("export ").partition("=")
        name = name.strip()
        if not separator or not name.isidentifier() or name.startswith("#"):
            continue
        environ.setdefault(name, unquote(value.strip()))


def unquote(value: str) -> str:
    """A quoted value runs to its closing quote, and anything after it (a comment) is
    dropped. An unquoted value ends at a `#` that follows a space or tab, so `a#b` stays."""
    if value[:1] in ("'", '"') and (end := value.find(value[0], 1)) > 0:
        return value[1:end]
    return COMMENT.split(value, maxsplit=1)[0].rstrip()


def describe_root_env(path: Path = ROOT_ENV) -> str:
    """The file a missing setting was looked for in, for error messages."""
    return str(path) if path.is_file() else f"{path} (not found: cp .env.example .env)"
