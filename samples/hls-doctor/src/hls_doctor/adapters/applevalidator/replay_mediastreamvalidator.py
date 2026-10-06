"""Fixture-backed validator replay; absent fixtures mean the crosscheck is skipped."""

from pathlib import Path

from hls_doctor.adapters.applevalidator.validator_report import (
    ValidateStream,
    ValidatorReport,
    parse_validator_output,
)
from media_ops_contracts.load_fixture import load_fixture
from media_ops_contracts.tool_failure import ToolFailure


def create_replay_validator(fixtures_dir: Path, scenario: str) -> ValidateStream:
    """Answers from fixtures/<scenario>/applevalidator.validate_stream.json."""

    def validate(url: str) -> ValidatorReport:
        try:
            recorded = load_fixture(fixtures_dir, scenario, "applevalidator.validate_stream")
        except ToolFailure:
            return ValidatorReport(
                url=url,
                available=False,
                unavailable_reason="No recorded validator output in this scenario.",
            )
        payload = recorded.get(url)
        if payload is None:
            return ValidatorReport(
                url=url,
                available=False,
                unavailable_reason="No recorded validator output for this URL.",
            )
        return parse_validator_output(url, payload)

    return validate
