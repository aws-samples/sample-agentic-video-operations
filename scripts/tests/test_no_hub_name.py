"""The hub sample is agentic-iops-streaming. No `hub` name comes back.

Word-level `hub` (so `github` and `MediaOpsHubStack` don't match) and the old package,
distribution, stack and setting names are refused in every tracked text file, except:
- the CHANGELOG, whose entries name what existed then (the rename's own entry included);
- the legacy `.hub-sessions` ignore entries, which keep an old local folder out of git and
  images and so must use its old name;
- the README upgrade note, which names the stack a user deletes by hand (that section only);
- the deploy's and the runtime's refusal of settings still set under their old HUB_* names,
  the doctor check that names them, the
  layout check that refuses `samples/hub/`, and `just clean`, which removes an upgraded
  clone's leftover `samples/hub/`, with their tests.
"""

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORD = re.compile(r"(?<![A-Za-z])hub(?![A-Za-z])", re.IGNORECASE)
OLD_NAMES = re.compile(r"media_ops_hub|media-ops-hub|MediaOpsHub|\bHUB_[A-Z]")
# `Hub` as one word of a CamelCase identifier: construct ids, IAM Sids, stack ids
# (InvokeHubPolicy, UseHubMemory, TestHub). GitHub is a name, not one of ours.
CAMEL = re.compile(r"(?<![A-Za-z])(?!GitHub)(?:[A-Z][a-z0-9]*)*Hub(?![a-z])")
LEGACY_IGNORE = ".hub-sessions"
ALLOWED = {
    "scripts/check_prerequisites.py": "the doctor warns about stale HUB_* settings",
    "scripts/tests/test_check_prerequisites.py": "it tests that warning",
    "scripts/tests/test_no_hub_name.py": "this guard",
    "scripts/check_repository_layout.py": "it refuses samples/hub/ coming back",
    "scripts/tests/test_check_repository_layout.py": "it tests that refusal",
    "scripts/clean_local_state.py": "it removes an upgraded clone's leftover samples/hub/",
    "scripts/renamed_settings.py": "the deploy refuses settings still named HUB_*",
    "scripts/tests/test_refuse_renamed_settings.py": "it tests that refusal",
    "samples/agentic-iops-streaming/src/agentic_iops_streaming/settings/"
    "refuse_renamed_settings.py": "the runtime refuses settings still named HUB_*",
    "samples/agentic-iops-streaming/tests/contract/"
    "test_agentic_iops_refuses_renamed_settings.py": "it tests that refusal",
    "scripts/tests/test_clean_local_state.py": "it tests that removal",
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
            if (
                WORD.search(line.replace(LEGACY_IGNORE, ""))
                or OLD_NAMES.search(line)
                or CAMEL.search(line)
            ):
                problems.append(f"{name}:{number}: {line.strip()[:100]}")
    assert problems == []


def test_the_guard_catches_a_reintroduced_name():
    assert WORD.search("Run the hub locally.")
    assert WORD.search("samples/hub/README.md")
    assert not WORD.search("https://github.com/aws-samples")
    assert not WORD.search("MediaOpsHubStack")
    assert OLD_NAMES.search("import media_ops_hub") and OLD_NAMES.search("HUB_WRITE_TAG=x")


@pytest.mark.parametrize(
    "line",
    [
        "new iam.ManagedPolicy(this, 'InvokeHubPolicy', {",
        "sid: 'InvokeHub',",
        "sid: 'UseHubMemory',",
        "new AgenticIopsStreamingStack(app, 'TestHub')",
        "class HubSettings:",
        '"Sid": "ReadHub"',
    ],
)
def test_the_guard_catches_camel_case_and_sid_forms(line):
    assert CAMEL.search(line)


@pytest.mark.parametrize(
    "line",
    ["See GitHub Actions.", "https://github.com/aws-samples", "Hubble telescope", "a hubcap"],
)
def test_the_camel_case_guard_leaves_other_words_alone(line):
    assert not CAMEL.search(line)
