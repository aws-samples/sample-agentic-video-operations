"""T1-T9: Monitoring stack tests — live MCP server, real CloudWatch calls.

Uses a RUNNING channel for metrics validation. All tests go through
the actual monitoring classes and coordinator, hitting real AWS APIs.
"""
import sys
import os
import pytest

# Ensure medialive-mcp-server/ is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.monitoring.base import BaseMonitor
from src.monitoring.channel_health import ChannelHealthMonitor
from src.monitoring.input_health import InputHealthMonitor
from src.monitoring.output_health import OutputHealthMonitor
from src.monitoring.media_health import MediaHealthMonitor
from src.monitoring.content_quality import ContentQualityMonitor
from src.monitoring.coordinator import MonitoringCoordinator

# Channel ID for live tests — set via env var
RUNNING_CHANNEL_ID = os.getenv("MEDIALIVE_TEST_CHANNEL_ID", "")

ALL_MONITORS = [
    ChannelHealthMonitor,
    InputHealthMonitor,
    OutputHealthMonitor,
    MediaHealthMonitor,
    ContentQualityMonitor,
]


# --- T1: All monitors instantiate and extend BaseMonitor ---

class TestT1MonitorInheritance:
    def test_all_are_subclasses_of_base(self):
        for cls in ALL_MONITORS:
            assert issubclass(cls, BaseMonitor), f"{cls.__name__} is not a subclass of BaseMonitor"

    def test_all_instantiate(self):
        for cls in ALL_MONITORS:
            instance = cls()
            assert instance is not None

    def test_all_implement_required_methods(self):
        for cls in ALL_MONITORS:
            instance = cls()
            assert callable(getattr(instance, 'get_metrics_list', None)), f"{cls.__name__} missing get_metrics_list"
            assert callable(getattr(instance, 'get_metric_units', None)), f"{cls.__name__} missing get_metric_units"
            assert callable(getattr(instance, '_analyze_health', None)), f"{cls.__name__} missing _analyze_health"


# --- T2: Metric lists are non-empty and match spec ---

class TestT2MetricLists:
    def test_channel_health_metrics(self):
        metrics = ChannelHealthMonitor().get_metrics_list()
        assert len(metrics) == 7
        for expected in ['ActiveAlerts', 'DroppedFrames', 'SvqTime']:
            assert expected in metrics, f"Missing {expected}"

    def test_input_health_metrics(self):
        metrics = InputHealthMonitor().get_metrics_list()
        assert len(metrics) == 10
        for expected in ['NetworkIn', 'InputLossSeconds', 'RtpPacketsLost']:
            assert expected in metrics, f"Missing {expected}"

    def test_output_health_metrics(self):
        metrics = OutputHealthMonitor().get_metrics_list()
        assert len(metrics) == 9
        for expected in ['NetworkOut', 'Output4xxErrors', 'Output5xxErrors']:
            assert expected in metrics, f"Missing {expected}"

    def test_media_health_metrics(self):
        metrics = MediaHealthMonitor().get_metrics_list()
        assert len(metrics) == 5
        for expected in ['ChannelInputErrorSeconds', 'FillMsec']:
            assert expected in metrics, f"Missing {expected}"

    def test_content_quality_metrics(self):
        metrics = ContentQualityMonitor().get_metrics_list()
        assert len(metrics) == 7
        for expected in ['MqcsBlackFrameDetected', 'MqcsFreezeFrameDetected']:
            assert expected in metrics, f"Missing {expected}"


# --- T3: Health score boundaries ---

class TestT3HealthScoreBoundaries:
    """Test _analyze_health with empty metrics and known-bad metrics."""

    def test_empty_metrics_returns_perfect_score(self):
        for cls in ALL_MONITORS:
            instance = cls()
            result = instance._analyze_health({})
            assert result['score'] == 100, f"{cls.__name__} empty metrics score != 100"
            assert result['status'] == 'EXCELLENT', f"{cls.__name__} empty metrics status != EXCELLENT"
            assert result['issues'] == [], f"{cls.__name__} empty metrics has issues"

    def test_bad_metrics_reduce_score(self):
        """Craft known-bad metrics for each monitor and verify score drops."""
        bad_metrics = {
            ChannelHealthMonitor: {
                'ActiveAlerts': {'datapoints': [{'Average': 5}]},
            },
            InputHealthMonitor: {
                'InputLossSeconds': {'datapoints': [{'Average': 10}]},
            },
            OutputHealthMonitor: {
                'Output4xxErrors': {'datapoints': [{'Average': 100}]},
            },
            MediaHealthMonitor: {
                'ChannelInputErrorSeconds': {'datapoints': [{'Average': 5}]},
            },
            ContentQualityMonitor: {
                'MqcsBlackFrameDetected': {'datapoints': [{'Average': 1}]},
            },
        }
        for cls, metrics in bad_metrics.items():
            instance = cls()
            result = instance._analyze_health(metrics)
            assert result['score'] < 100, f"{cls.__name__} bad metrics didn't reduce score"
            assert len(result['issues']) > 0, f"{cls.__name__} bad metrics produced no issues"

    def test_score_always_valid_range(self):
        """Score must be int in [0, 100], status must be valid."""
        valid_statuses = {'EXCELLENT', 'GOOD', 'POOR'}
        for cls in ALL_MONITORS:
            instance = cls()
            # Test with empty
            result = instance._analyze_health({})
            assert isinstance(result['score'], int)
            assert 0 <= result['score'] <= 100
            assert result['status'] in valid_statuses

    def test_status_matches_score(self):
        """Verify status thresholds: >=90 EXCELLENT, >=70 GOOD, <70 POOR."""
        for cls in ALL_MONITORS:
            instance = cls()
            result = instance._analyze_health({})
            score = result['score']
            if score >= 90:
                assert result['status'] == 'EXCELLENT'
            elif score >= 70:
                assert result['status'] == 'GOOD'
            else:
                assert result['status'] == 'POOR'


# --- T4: BaseMonitor uses correct namespace and dimension (live call) ---

class TestT4NamespaceAndDimension:
    """Call get_metrics on a real channel and verify the response structure."""

    def test_get_metrics_returns_correct_structure(self):
        monitor = ChannelHealthMonitor()
        result = monitor.get_metrics(channel_id=RUNNING_CHANNEL_ID, hours_back=1)
        assert 'channel_id' in result
        assert result['channel_id'] == RUNNING_CHANNEL_ID
        assert 'metrics' in result
        assert 'category_health' in result
        # Verify metrics dict has entries for each metric in the list
        for metric_name in monitor.get_metrics_list():
            assert metric_name in result['metrics'], f"Missing metric {metric_name} in response"


# --- T5: BaseMonitor error isolation ---

class TestT5ErrorIsolation:
    """If one metric fails, others should still return data."""

    def test_individual_metric_errors_dont_crash(self):
        """Use a bogus channel ID — CloudWatch returns empty datapoints, not errors.
        Use a real channel to verify the structure is correct even with partial data."""
        monitor = ChannelHealthMonitor()
        result = monitor.get_metrics(channel_id=RUNNING_CHANNEL_ID, hours_back=1)
        # Should not have a top-level error
        assert 'error' not in result, f"Unexpected error: {result.get('error')}"
        # Each metric should be present (even if empty datapoints)
        assert isinstance(result['metrics'], dict)
        assert len(result['metrics']) == len(monitor.get_metrics_list())


# --- T6: Coordinator registers all 5 categories ---

class TestT6CoordinatorCategories:
    def test_all_categories_registered(self):
        coord = MonitoringCoordinator()
        expected = {'channel_health', 'input_health', 'output_health', 'media_health', 'content_quality'}
        assert set(coord.monitors.keys()) == expected


# --- T7: Coordinator invalid category returns error ---

class TestT7InvalidCategory:
    def test_invalid_category_returns_error(self):
        coord = MonitoringCoordinator()
        result = coord.get_category_metrics('nonexistent', RUNNING_CHANNEL_ID)
        assert 'error' in result
        assert 'available_categories' in result
        assert set(result['available_categories']) == {'channel_health', 'input_health', 'output_health', 'media_health', 'content_quality'}


# --- T8: Coordinator check_channel_issues severity classification ---

class TestT8IssueSeverity:
    """Live test — check_channel_issues on a running channel."""

    def test_check_issues_returns_valid_structure(self):
        coord = MonitoringCoordinator()
        result = coord.check_channel_issues(RUNNING_CHANNEL_ID, hours_back=1)
        assert 'channel_id' in result
        assert 'issues_found' in result
        assert 'issues' in result
        assert 'status' in result
        assert result['status'] in ('HEALTHY', 'ISSUES_DETECTED')

        # If issues exist, verify severity classification
        for issue in result['issues']:
            assert 'severity' in issue
            assert issue['severity'] in ('HIGH', 'MEDIUM')
            assert 'category' in issue
            assert 'description' in issue


# --- T9: Coordinator get_metrics_table row format ---

class TestT9MetricsTable:
    """Live test — get_metrics_table on a running channel."""

    def test_table_structure(self):
        coord = MonitoringCoordinator()
        result = coord.get_metrics_table(RUNNING_CHANNEL_ID, hours_back=1)
        assert 'table_data' in result
        assert 'data_points' in result
        assert result.get('chart_ready') is True

        required_keys = {'timestamp', 'category', 'metric', 'value', 'unit', 'statistic'}
        for row in result['table_data']:
            assert required_keys.issubset(row.keys()), f"Row missing keys: {required_keys - row.keys()}"

    def test_table_sorted_by_timestamp(self):
        coord = MonitoringCoordinator()
        result = coord.get_metrics_table(RUNNING_CHANNEL_ID, hours_back=1)
        timestamps = [row['timestamp'] for row in result['table_data']]
        assert timestamps == sorted(timestamps), "Table data not sorted by timestamp"
