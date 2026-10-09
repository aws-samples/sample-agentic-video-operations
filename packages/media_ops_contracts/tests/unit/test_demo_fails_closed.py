"""Demo mode never builds a boto3 client."""

import pytest

from media_ops_contracts import create_aws_client as module
from media_ops_contracts.create_aws_client import create_aws_client
from media_ops_contracts.resolve_demo_scenario import resolve_demo_scenario
from media_ops_contracts.tool_failure import FailureKind, ToolFailure


@pytest.fixture
def boto3_forbidden(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("demo mode built a real boto3 client")

    monkeypatch.setattr(module.boto3, "client", refuse)


@pytest.fixture
def fixtures_dir(tmp_path):
    (tmp_path / "input_loss").mkdir()
    return tmp_path


@pytest.mark.parametrize("scenario", ["", "missing_scenario"])
def test_demo_with_an_empty_or_unknown_scenario_fails_closed(
    boto3_forbidden, fixtures_dir, scenario
):
    with pytest.raises(ToolFailure) as failure:
        create_aws_client(
            "medialive", region="us-west-2", demo=True, demo_scenario=scenario,
            fixtures_dir=fixtures_dir,
        )  # fmt: skip
    assert failure.value.kind is FailureKind.INVALID_REQUEST


def test_without_demo_a_regional_boto3_client_is_built(monkeypatch):
    calls = []
    monkeypatch.setattr(module.boto3, "client", lambda *a, **k: calls.append((a, k)) or "real")
    assert create_aws_client("medialive", region="eu-west-1", demo=False) == "real"
    assert calls[0][1]["region_name"] == "eu-west-1"


@pytest.mark.parametrize(("value", "expected"), [("", "input_loss"), (None, "input_loss"),
                                                 ("  ", "input_loss"), ("srt", "srt")])  # fmt: skip
def test_an_empty_scenario_means_the_sample_default(value, expected):
    assert resolve_demo_scenario(value, "input_loss") == expected
