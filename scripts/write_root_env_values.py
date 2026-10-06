"""Update selected root .env values without printing their contents."""

import os
import tempfile
from collections.abc import Mapping
from pathlib import Path


def replace_env_values(content: str, values: Mapping[str, str]) -> str:
    configured = dict(values)
    pending = dict(values)
    written: set[str] = set()
    lines: list[str] = []
    for line in content.splitlines():
        key = line.split("=", 1)[0] if "=" in line and not line.lstrip().startswith("#") else ""
        if key in configured:
            if key not in written:
                lines.append(f"{key}={configured[key]}")
                written.add(key)
            pending.pop(key, None)
        else:
            lines.append(line)
    if pending and lines and lines[-1]:
        lines.append("")
    lines.extend(f"{key}={value}" for key, value in pending.items())
    return "\n".join(lines) + "\n"


def write_root_env_values(
    env_path: Path,
    example_path: Path,
    values: Mapping[str, str],
) -> None:
    """Preserve unrelated settings and atomically write a private root .env."""
    source_path = env_path if env_path.exists() else example_path
    content = source_path.read_text() if source_path.exists() else ""
    updated = replace_env_values(content, values)
    env_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=env_path.parent,
            prefix=f".{env_path.name}.",
            delete=False,
        ) as temporary:
            temporary.write(updated)
            temporary_name = temporary.name
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, env_path)
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)
