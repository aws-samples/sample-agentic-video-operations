"""A channel with almost no input publishes only six metrics; the rest is NOT_EMITTED."""

from pathlib import Path

from medialive_mcp.bootstrap.create_medialive_clients import create_medialive_clients
from medialive_mcp.settings.runtime_settings import RuntimeSettings
from medialive_mcp.workflows.check_channel_health import check_channel_issues

PUBLISHED = {
    "ActiveAlerts", "ComplexFrcPresent", "FillMsec", "NetworkIn", "NetworkOut",
    "PipelinesLocked",
}  # fmt: skip
FIXTURES = Path(__file__).resolve().parents[4] / "fixtures"


def test_no_input_reports_fill_frames_and_lists_every_silent_metric():
    settings = RuntimeSettings(demo=True, demo_scenario="no_input", fixtures_dir=FIXTURES)
    report = check_channel_issues(create_medialive_clients(settings), "1234567", hours_back=1)

    flagged = {(issue.metric, issue.pipeline) for issue in report.issues}
    assert {("FillMsec", "0"), ("FillMsec", "1"), ("ActiveAlerts", "0")} <= flagged
    assert "InputLossSeconds" in report.not_emitted
    assert "MinMQCS" in report.not_emitted
    assert PUBLISHED.isdisjoint(report.not_emitted)
    assert report.categories["content_quality"].status != "HEALTHY"
    assert report.status == "DEGRADED"
