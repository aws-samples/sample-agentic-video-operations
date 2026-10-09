"""Run Apple's mediastreamvalidator and parse its JSON validation data."""

import json
import subprocess
import tempfile
from pathlib import Path

from hls_doctor.adapters.applevalidator.locate_mediastreamvalidator import (
    locate_mediastreamvalidator,
)
from hls_doctor.adapters.applevalidator.validator_report import (
    ValidateStream,
    ValidatorReport,
    parse_validator_output,
)
from hls_doctor.adapters.http.guard_fetch_target import guard_fetch_target

VALIDATOR_TIMEOUT_SECONDS = 300


def create_live_validator(*, allow_private_targets: bool = False) -> ValidateStream:
    """A ValidateStream backed by the local mediastreamvalidator binary."""

    def validate(url: str) -> ValidatorReport:
        guard_fetch_target(url, allow_private=allow_private_targets)
        binary = locate_mediastreamvalidator()
        with tempfile.TemporaryDirectory(prefix="hls-doctor-msv-") as workdir:
            output = Path(workdir) / "validation_data.json"
            completed = subprocess.run(
                [binary, "--validation-data-path", str(output), url],
                capture_output=True,
                text=True,
                timeout=VALIDATOR_TIMEOUT_SECONDS,
                check=False,
            )
            if not output.is_file():
                reason = completed.stderr.strip().splitlines()[-1][:200] if completed.stderr else ""
                return ValidatorReport(
                    url=url,
                    available=False,
                    unavailable_reason=reason or f"validator exited with {completed.returncode}",
                )
            return parse_validator_output(url, json.loads(output.read_text()))

    return validate
