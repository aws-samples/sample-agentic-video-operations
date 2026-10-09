"""Run the hls.js harness as a subprocess and parse its JSON report."""

import json
import subprocess

from hls_doctor.adapters.hlsjs.locate_player_probe import locate_player_probe
from hls_doctor.adapters.hlsjs.player_probe_report import PlayerProbeReport
from media_ops_contracts.tool_failure import FailureKind, ToolFailure

HARNESS_TIMEOUT_SECONDS = 120


def run_player_probe(url: str, duration_seconds: float = 10) -> PlayerProbeReport:
    node, script = locate_player_probe()
    completed = subprocess.run(
        [node, str(script), url, str(duration_seconds)],
        capture_output=True,
        text=True,
        timeout=HARNESS_TIMEOUT_SECONDS,
        check=False,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        detail = completed.stderr.strip().splitlines()[-1][:200] if completed.stderr else ""
        raise ToolFailure(
            FailureKind.EXTERNAL_SERVICE_UNAVAILABLE,
            f"The player probe did not produce a report: {detail or 'empty output'}.",
            "Check that Chromium is available to playwright-core and the URL is reachable.",
        )
    return parse_player_report(completed.stdout)


def parse_player_report(payload: str) -> PlayerProbeReport:
    try:
        return PlayerProbeReport.model_validate(json.loads(payload))
    except (json.JSONDecodeError, ValueError) as error:
        raise ToolFailure(
            FailureKind.UNEXPECTED_FAILURE,
            f"The player probe's output could not be parsed: {type(error).__name__}.",
            "Re-run the probe; report the issue if it persists.",
        ) from error
