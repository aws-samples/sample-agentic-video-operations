"""The live cmcd MCP server process starts without INFLUXDB_* settings."""

import os
import subprocess
import sys

import pytest


@pytest.mark.slow  # starts the real server process
def test_the_live_server_process_starts_without_a_traceback():
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(("INFLUXDB_", "AWS_")) and name != "DEMO"
    }
    result = subprocess.run(
        [sys.executable, "-m", "cmcd_mcp.entrypoints.serve_mcp"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
        env=environment,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr
    assert "Starting MCP server" in result.stderr
