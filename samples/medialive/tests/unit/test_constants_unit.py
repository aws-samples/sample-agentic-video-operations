"""T21-T23: Environment-driven config in constants.py."""
import os
import importlib
import pytest

from src.tools.constants import get_channel_id


# ── T21 — DEFAULT_CHANNEL_ID reads from env var ─────────────────────────

class TestT21EnvVar:
    def test_reads_env_var(self, monkeypatch):
        monkeypatch.setenv("MEDIALIVE_DEFAULT_CHANNEL_ID", "TEST999")
        import src.tools.constants as mod
        importlib.reload(mod)
        assert mod.DEFAULT_CHANNEL_ID == "TEST999"
        # Restore
        monkeypatch.delenv("MEDIALIVE_DEFAULT_CHANNEL_ID", raising=False)
        importlib.reload(mod)


# ── T22 — get_channel_id returns explicit channel_id when provided ───────

class TestT22Explicit:
    def test_explicit_wins(self):
        assert get_channel_id("EXPLICIT") == "EXPLICIT"


# ── T23 — get_channel_id raises ValueError when no channel_id and no env ─

class TestT23NoDefault:
    def test_raises_value_error(self, monkeypatch):
        monkeypatch.delenv("MEDIALIVE_DEFAULT_CHANNEL_ID", raising=False)
        import src.tools.constants as mod
        importlib.reload(mod)
        with pytest.raises(ValueError, match="MEDIALIVE_DEFAULT_CHANNEL_ID"):
            mod.get_channel_id(None)
        # Restore
        importlib.reload(mod)
