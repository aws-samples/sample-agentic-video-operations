"""Local session files live under the ignored .cache/ (T65).

They hold operators' conversations and pending approvals. The old default `.hub-sessions`
was neither git-ignored nor kept out of image build contexts.
"""

import subprocess
from pathlib import Path

from agentic_iops_streaming.settings.runtime_settings import AgenticIopsSettings

ROOT = Path(__file__).resolve().parents[2]


def test_the_default_session_dir_is_under_the_ignored_cache():
    assert AgenticIopsSettings.model_fields["session_dir"].default == Path(
        ".cache/agentic-iops-sessions"
    )
    assert "SESSION_DIR=.cache/agentic-iops-sessions" in (ROOT / ".env.example").read_text()


def test_session_files_old_and_new_are_ignored_by_git():
    for path in (".cache/agentic-iops-sessions/actor_x/s.json", ".hub-sessions/actor_x/s.json"):
        ignored = subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT)
        assert ignored.returncode == 0, f"{path} is not git-ignored"


def test_the_agentic_iops_image_asset_excludes_old_session_files():
    stack = (
        ROOT / "samples/agentic-iops-streaming/cdk/lib/agentic-iops-streaming-stack.ts"
    ).read_text()
    assert "'**/.hub-sessions'" in stack


def test_a_session_dir_inside_the_repository_must_be_under_cache(tmp_path, monkeypatch):
    """T65 review: SESSION_DIR=custom-sessions would be committed and copied into images."""
    import pytest
    from pydantic import ValidationError

    monkeypatch.chdir(tmp_path)
    for unsafe in ("custom-sessions", ".cache/../sessions", str(tmp_path / "sessions"), "."):
        with pytest.raises(ValidationError, match="SESSION_DIR"):
            AgenticIopsSettings(session_dir=Path(unsafe))
    for safe in (".cache/agentic-iops-sessions", ".cache/other", str(tmp_path / ".cache" / "s")):
        assert AgenticIopsSettings(session_dir=Path(safe)).session_dir == Path(safe)


def test_a_session_dir_outside_the_working_directory_is_the_operators_to_protect(
    tmp_path, monkeypatch
):
    repository = tmp_path / "repository"
    repository.mkdir()
    monkeypatch.chdir(repository)
    outside = tmp_path / "state" / "agentic-iops-sessions"
    assert AgenticIopsSettings(session_dir=outside).session_dir == outside
