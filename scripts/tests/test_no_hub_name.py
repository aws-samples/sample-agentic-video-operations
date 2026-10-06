"""REN1: the hub sample is agentic-iops-streaming. No `hub` name comes back.

Word-level `hub` (so `github` and `MediaOpsHubStack` don't match) and the old package,
distribution, stack and setting names are refused in every tracked text file, except:
- the CHANGELOG, whose entries name what existed then (the rename's own entry included);
- the legacy `.hub-sessions` ignore entries, which keep an old local folder out of git and
  images and so must use its old name;
- the README upgrade note, which names the stack a user deletes by hand (that section only);
- the doctor check that warns about settings still set under their old HUB_* names, and
  the layout check that refuses `samples/hub/`, with their tests.
"""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORD = re.compile(r"(?<![A-Za-z])hub(?![A-Za-z])", re.IGNORECASE)
OLD_NAMES = re.compile(r"media_ops_hub|media-ops-hub|MediaOpsHub|\bHUB_[A-Z]")
LEGACY_IGNORE = ".hub-sessions"
ALLOWED = {
    "scripts/check_prerequisites.py": "the doctor warns about stale HUB_* settings",
    "scripts/tests/test_check_prerequisites.py": "it tests that warning",
    "scripts/tests/test_no_hub_name.py": "this guard",
    "scripts/check_repository_layout.py": "it refuses samples/hub/ coming back",
    "scripts/tests/test_check_repository_layout.py": "it tests that refusal",
}
SKIPPED = {"uv.lock", "CHANGELOG.md"}
README = "samples/agentic-iops-streaming/README.md"
UPGRADE_NOTE = "### Upgrading from the hub sample"


def without_upgrade_note(text: str) -> str:
    """The README minus its upgrade note, which has to name the old stack and sample."""
    start = text.index(UPGRADE_NOTE)
    end = text.find("\n## ", start)
    return text[:start] + (text[end:] if end > 0 else "")


def tracked_text_files():
    names = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    for name in names:
        if Path(name).name in SKIPPED:
            continue
        try:
            yield name, (ROOT / name).read_text()
        except (UnicodeDecodeError, FileNotFoundError):
            continue  # binary files (images)


def test_no_hub_name_outside_changelog_history():
    problems = []
    for name, text in tracked_text_files():
        if name in ALLOWED:
            continue
        if name == README:
            text = without_upgrade_note(text)
        for number, line in enumerate(text.splitlines(), 1):
            if WORD.search(line.replace(LEGACY_IGNORE, "")) or OLD_NAMES.search(line):
                problems.append(f"{name}:{number}: {line.strip()[:100]}")
    assert problems == []


def test_the_guard_catches_a_reintroduced_name():
    assert WORD.search("Run the hub locally.")
    assert WORD.search("samples/hub/README.md")
    assert not WORD.search("https://github.com/aws-samples")
    assert not WORD.search("MediaOpsHubStack")
    assert OLD_NAMES.search("import media_ops_hub") and OLD_NAMES.search("HUB_WRITE_TAG=x")
