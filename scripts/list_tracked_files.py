"""List repository files from Git rather than local filesystem state."""

import subprocess
from pathlib import Path


def list_tracked_files(root: Path, *pathspecs: str) -> tuple[Path, ...]:
    """Return tracked files matching the optional Git pathspecs."""
    command = ["git", "ls-files", "-z"]
    if pathspecs:
        command.extend(["--", *pathspecs])
    result = subprocess.run(
        command,
        cwd=root,
        capture_output=True,
        check=True,
    )
    names = result.stdout.decode().split("\0")
    return tuple(root / name for name in names if name)
