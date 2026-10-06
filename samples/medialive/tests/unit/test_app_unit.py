"""T17-T20: Composite tool dispatch in app.py — all deps mocked."""
import json
import pytest
from unittest.mock import patch, MagicMock


# ── T17 — app.py exports channel_health_monitoring ───────────────────────

class TestT17Export:
    def test_import_channel_health_monitoring(self):
        from src.app import channel_health_monitoring
        assert callable(channel_health_monitoring)


# ── T18 — channel_health_monitoring dispatches all_metrics ───────────────

class TestT18AllMetrics:
    def test_dispatches_all_metrics(self):
        import src.app as app_mod
        mock_coord = MagicMock()
        mock_coord.get_all_metrics.return_value = {"test": True}
        original = app_mod._monitoring_coordinator
        app_mod._monitoring_coordinator = mock_coord
        try:
            result = app_mod.channel_health_monitoring(
                action="all_metrics", channel_id="123"
            )
            mock_coord.get_all_metrics.assert_called_once_with("123", 1)
            parsed = json.loads(result)
            assert parsed["test"] is True
        finally:
            app_mod._monitoring_coordinator = original


# ── T19 — channel_health_monitoring dispatches category_metrics ──────────

class TestT19CategoryMetrics:
    def test_dispatches_category_metrics(self):
        import src.app as app_mod
        mock_coord = MagicMock()
        mock_coord.get_category_metrics.return_value = {"cat": True}
        original = app_mod._monitoring_coordinator
        app_mod._monitoring_coordinator = mock_coord
        try:
            result = app_mod.channel_health_monitoring(
                action="category_metrics",
                channel_id="123",
                category="input_health",
            )
            mock_coord.get_category_metrics.assert_called_once_with(
                "input_health", "123", 1
            )
            parsed = json.loads(result)
            assert parsed["cat"] is True
        finally:
            app_mod._monitoring_coordinator = original


# ── T20 — channel_health_monitoring returns error on invalid action ──────

class TestT20InvalidAction:
    def test_invalid_action_returns_error(self):
        import src.app as app_mod
        result = app_mod.channel_health_monitoring(
            action="bogus", channel_id="123"
        )
        parsed = json.loads(result)
        assert "error" in parsed
        assert "valid_actions" in parsed
        assert sorted(parsed["valid_actions"]) == sorted(
            ["all_metrics", "category_metrics", "check_issues", "metrics_table"]
        )
