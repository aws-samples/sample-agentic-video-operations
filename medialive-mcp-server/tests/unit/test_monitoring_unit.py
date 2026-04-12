"""T1-T9: Monitoring stack unit tests — all boto3 calls mocked."""
import pytest
from unittest.mock import patch, MagicMock

from src.monitoring.base import BaseMonitor
from src.monitoring.channel_health import ChannelHealthMonitor
from src.monitoring.input_health import InputHealthMonitor
from src.monitoring.output_health import OutputHealthMonitor
from src.monitoring.media_health import MediaHealthMonitor
from src.monitoring.content_quality import ContentQualityMonitor
from src.monitoring.coordinator import MonitoringCoordinator


# ── Helpers ──────────────────────────────────────────────────────────────

MONITOR_CLASSES = [
    ChannelHealthMonitor,
    InputHealthMonitor,
    OutputHealthMonitor,
    MediaHealthMonitor,
    ContentQualityMonitor,
]


def _make_monitor(cls):
    """Instantiate a monitor with a mocked CloudWatch client."""
    with patch("boto3.client"):
        m = cls()
    m.cloudwatch = MagicMock()
    return m


# ── T1 — All 5 monitors extend BaseMonitor ──────────────────────────────

class TestT1Subclass:
    @pytest.mark.parametrize("cls", MONITOR_CLASSES)
    def test_is_subclass_of_base(self, cls):
        assert issubclass(cls, BaseMonitor)

    @pytest.mark.parametrize("cls", MONITOR_CLASSES)
    def test_has_required_methods(self, cls):
        for method in ("get_metrics_list", "get_metric_units", "_analyze_health"):
            assert hasattr(cls, method) and callable(getattr(cls, method))


# ── T2 — Metric list counts match spec ───────────────────────────────────

class TestT2MetricCounts:
    def test_channel_health_count(self):
        m = _make_monitor(ChannelHealthMonitor)
        assert len(m.get_metrics_list()) == 7

    def test_input_health_count(self):
        m = _make_monitor(InputHealthMonitor)
        assert len(m.get_metrics_list()) == 10

    def test_output_health_count(self):
        m = _make_monitor(OutputHealthMonitor)
        assert len(m.get_metrics_list()) == 9

    def test_media_health_count(self):
        m = _make_monitor(MediaHealthMonitor)
        assert len(m.get_metrics_list()) == 5

    def test_content_quality_count(self):
        m = _make_monitor(ContentQualityMonitor)
        assert len(m.get_metrics_list()) == 7


# ── T3 — Metric lists contain required metrics ──────────────────────────

class TestT3RequiredMetrics:
    def test_channel_required(self):
        metrics = _make_monitor(ChannelHealthMonitor).get_metrics_list()
        for name in ("ActiveAlerts", "PipelinesLocked", "FillMsec", "DroppedFrames", "SvqTime"):
            assert name in metrics

    def test_input_required(self):
        metrics = _make_monitor(InputHealthMonitor).get_metrics_list()
        for name in ("NetworkIn", "InputLossSeconds", "RtpPacketsLost", "ChannelInputErrorSeconds"):
            assert name in metrics

    def test_output_required(self):
        metrics = _make_monitor(OutputHealthMonitor).get_metrics_list()
        for name in ("NetworkOut", "Output4xxErrors", "Output5xxErrors", "DroppedFrames"):
            assert name in metrics

    def test_media_required(self):
        metrics = _make_monitor(MediaHealthMonitor).get_metrics_list()
        for name in ("ChannelInputErrorSeconds", "FillMsec", "InputTimecodesPresent"):
            assert name in metrics

    def test_content_quality_required(self):
        metrics = _make_monitor(ContentQualityMonitor).get_metrics_list()
        for name in ("MqcsBlackFrameDetected", "MqcsFreezeFrameDetected", "MqcsContinuityCounterErrors"):
            assert name in metrics


# ── T4 — Health score with empty metrics returns EXCELLENT ───────────────

class TestT4EmptyMetrics:
    @pytest.mark.parametrize("cls", MONITOR_CLASSES)
    def test_empty_metrics_excellent(self, cls):
        m = _make_monitor(cls)
        result = m._analyze_health({})
        assert result["score"] == 100
        assert result["status"] == "EXCELLENT"
        assert result["issues"] == []


# ── T5 — Health score with bad metrics returns degraded score ────────────

class TestT5BadMetrics:
    def _bad_datapoints(self, metric_name, avg=5.0):
        return {metric_name: {"datapoints": [{"Average": avg}]}}

    def test_channel_active_alerts(self):
        m = _make_monitor(ChannelHealthMonitor)
        result = m._analyze_health(self._bad_datapoints("ActiveAlerts"))
        assert result["score"] < 100
        assert len(result["issues"]) > 0

    def test_input_loss_seconds(self):
        m = _make_monitor(InputHealthMonitor)
        result = m._analyze_health(self._bad_datapoints("InputLossSeconds"))
        assert result["score"] < 100

    def test_output_5xx_errors(self):
        m = _make_monitor(OutputHealthMonitor)
        result = m._analyze_health(self._bad_datapoints("Output5xxErrors"))
        assert result["score"] < 100

    def test_media_input_error_seconds(self):
        m = _make_monitor(MediaHealthMonitor)
        result = m._analyze_health(self._bad_datapoints("ChannelInputErrorSeconds"))
        assert result["score"] < 100

    def test_content_black_frame(self):
        m = _make_monitor(ContentQualityMonitor)
        result = m._analyze_health(self._bad_datapoints("MqcsBlackFrameDetected"))
        assert result["score"] < 100

    @pytest.mark.parametrize("cls", MONITOR_CLASSES)
    def test_score_is_int_in_range(self, cls):
        m = _make_monitor(cls)
        # Use a metric that exists for each monitor
        metric = m.get_metrics_list()[0]
        result = m._analyze_health({metric: {"datapoints": [{"Average": 5.0}]}})
        assert isinstance(result["score"], int)
        assert 0 <= result["score"] <= 100

    @pytest.mark.parametrize("cls", MONITOR_CLASSES)
    def test_status_classification(self, cls):
        m = _make_monitor(cls)
        # EXCELLENT
        r = m._analyze_health({})
        assert r["score"] >= 90
        assert r["status"] == "EXCELLENT"


# ── T6 — BaseMonitor uses AWS/MediaLive namespace and ChannelId dimension ─

class TestT6CloudWatchCall:
    def test_namespace_and_dimensions(self):
        m = _make_monitor(ChannelHealthMonitor)
        m.cloudwatch.get_metric_statistics.return_value = {
            "Datapoints": [{"Timestamp": "2024-01-01T00:00:00Z", "Average": 0, "Unit": "Count"}]
        }
        m.get_metrics(channel_id="TEST123", hours_back=1)

        calls = m.cloudwatch.get_metric_statistics.call_args_list
        assert len(calls) > 0
        first_call = calls[0]
        kwargs = first_call.kwargs if first_call.kwargs else {}
        if not kwargs:
            # positional-only fallback
            kwargs = first_call[1] if len(first_call) > 1 else {}

        assert kwargs["Namespace"] == "AWS/MediaLive"
        dims = kwargs["Dimensions"]
        assert {"Name": "ChannelId", "Value": "TEST123"} in dims
        assert {"Name": "Pipeline", "Value": "0"} in dims


# ── T7 — BaseMonitor error isolation ─────────────────────────────────────

class TestT7ErrorIsolation:
    def test_first_metric_error_others_ok(self):
        m = _make_monitor(ChannelHealthMonitor)
        call_count = 0

        def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("boom")
            return {"Datapoints": [{"Timestamp": "2024-01-01T00:00:00Z", "Average": 0, "Unit": "Count"}]}

        m.cloudwatch.get_metric_statistics.side_effect = side_effect
        result = m.get_metrics(channel_id="123", hours_back=1)

        metrics = result["metrics"]
        metric_names = list(metrics.keys())
        # First metric should have error
        assert "error" in metrics[metric_names[0]]
        # Remaining metrics should have datapoints
        for name in metric_names[1:]:
            assert "datapoints" in metrics[name]


# ── T8 — Coordinator registers all 5 categories ─────────────────────────

class TestT8Coordinator:
    def test_all_categories_registered(self):
        with patch("boto3.client"):
            coord = MonitoringCoordinator()
        expected = {"channel_health", "input_health", "output_health", "media_health", "content_quality"}
        assert set(coord.monitors.keys()) == expected

    def test_all_values_are_base_monitor(self):
        with patch("boto3.client"):
            coord = MonitoringCoordinator()
        for monitor in coord.monitors.values():
            assert isinstance(monitor, BaseMonitor)


# ── T9 — Coordinator invalid category returns error ──────────────────────

class TestT9InvalidCategory:
    def test_invalid_category_error(self):
        with patch("boto3.client"):
            coord = MonitoringCoordinator()
        result = coord.get_category_metrics("nonexistent", "123")
        assert "error" in result
        assert "nonexistent" in result["error"]
        assert "available_categories" in result
        assert len(result["available_categories"]) == 5
