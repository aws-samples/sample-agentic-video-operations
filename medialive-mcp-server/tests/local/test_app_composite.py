"""T15-T16: app.py composite tool tests — verify channel_health_monitoring dispatch."""
import sys
import os
import json
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.app import channel_health_monitoring

# Channel ID for live tests — set via env var
RUNNING_CHANNEL_ID = os.getenv("MEDIALIVE_TEST_CHANNEL_ID", "")


# --- T15: app.py exports channel_health_monitoring ---

class TestT15Export:
    def test_importable(self):
        assert channel_health_monitoring is not None

    def test_callable(self):
        assert callable(channel_health_monitoring)


# --- T16: channel_health_monitoring dispatches correctly (live) ---

class TestT16Dispatch:
    def test_all_metrics_action(self):
        result_str = channel_health_monitoring(action='all_metrics', channel_id=RUNNING_CHANNEL_ID)
        result = json.loads(result_str)
        assert 'channel_id' in result or 'metrics_by_category' in result
        assert 'error' not in result, f"Unexpected error: {result.get('error')}"

    def test_category_metrics_action(self):
        result_str = channel_health_monitoring(
            action='category_metrics', channel_id=RUNNING_CHANNEL_ID, category='input_health'
        )
        result = json.loads(result_str)
        assert 'error' not in result, f"Unexpected error: {result.get('error')}"
        assert 'metrics' in result

    def test_check_issues_action(self):
        result_str = channel_health_monitoring(action='check_issues', channel_id=RUNNING_CHANNEL_ID)
        result = json.loads(result_str)
        assert 'status' in result
        assert result['status'] in ('HEALTHY', 'ISSUES_DETECTED')

    def test_metrics_table_action(self):
        result_str = channel_health_monitoring(action='metrics_table', channel_id=RUNNING_CHANNEL_ID)
        result = json.loads(result_str)
        assert 'table_data' in result
        assert result.get('chart_ready') is True

    def test_invalid_action_returns_error(self):
        result_str = channel_health_monitoring(action='bogus', channel_id=RUNNING_CHANNEL_ID)
        result = json.loads(result_str)
        assert 'error' in result
        assert 'valid_actions' in result
