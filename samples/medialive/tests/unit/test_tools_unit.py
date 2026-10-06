"""T10-T14: Tool imports and error handling — all AWS calls mocked."""
import pytest
from unittest.mock import patch, MagicMock


# ── T10 — All 15 tool functions import from src.tools ────────────────────

class TestT10ToolExports:
    def test_all_count(self):
        from src.tools import __all__
        assert len(__all__) == 15

    def test_all_callable(self):
        import src.tools as tools_mod
        from src.tools import __all__
        for name in __all__:
            fn = getattr(tools_mod, name)
            assert callable(fn), f"{name} is not callable"


# ── T11 — current_time returns ISO string ────────────────────────────────

class TestT11CurrentTime:
    def test_returns_iso_string(self):
        from src.tools import current_time
        result = current_time()
        assert isinstance(result, str)
        assert "T" in result  # ISO 8601 separator


# ── T12 — list_channels returns string on error ─────────────────────────

class TestT12ListChannelsError:
    def test_error_returns_string(self):
        from src.tools import medialive_tools
        original = medialive_tools.medialive
        mock_client = MagicMock()
        mock_client.get_paginator.side_effect = Exception("test error")
        medialive_tools.medialive = mock_client
        try:
            result = medialive_tools.list_channels()
            assert isinstance(result, str)
            assert "Error" in result or "error" in result
        finally:
            medialive_tools.medialive = original


# ── T13 — describe_channel returns string on error ───────────────────────

class TestT13DescribeChannelError:
    def test_error_returns_string(self):
        from src.tools import medialive_tools
        original = medialive_tools.medialive
        mock_client = MagicMock()
        mock_client.describe_channel.side_effect = Exception("test error")
        medialive_tools.medialive = mock_client
        try:
            result = medialive_tools.describe_channel("123")
            assert isinstance(result, str)
            assert "Error" in result
        finally:
            medialive_tools.medialive = original


# ── T14 — get_channel_metrics returns string on error ────────────────────

class TestT14GetChannelMetricsError:
    def test_error_returns_string(self):
        from src.tools import medialive_tools
        original_cw = medialive_tools.cloudwatch
        mock_cw = MagicMock()
        mock_cw.get_metric_statistics.side_effect = Exception("test error")
        medialive_tools.cloudwatch = mock_cw
        try:
            result = medialive_tools.get_channel_metrics("123", 1)
            assert isinstance(result, str)
            assert "Error" in result or "error" in result
        finally:
            medialive_tools.cloudwatch = original_cw
