"""MCP servers start without the FastMCP banner, its hosting link or its upgrade nag.

The banner is also the only place FastMCP checks PyPI for a newer version, so without it a
server makes no update request either.
"""

import os
import subprocess
import sys

import pytest

SERVERS = (
    "cmcd_mcp.entrypoints.serve_mcp",
    "mediaconnect_mcp.entrypoints.serve_mcp",
    "medialive_mcp.entrypoints.serve_mcp",
    "hls_doctor.entrypoints.serve_mcp",
)
BANNER_TEXT = ("╭", "FastMCP", "pip install --upgrade", "horizon.prefect.io", "gofastmcp.com")


@pytest.mark.slow  # starts the real server process
@pytest.mark.parametrize("module", SERVERS)
def test_a_server_writes_no_banner_to_stderr(module):
    environment = {
        name: value for name, value in os.environ.items() if not name.startswith("AWS_")
    } | {
        "DEMO": "1",
        "AWS_REGION": "us-west-2",
        "AWS_CONFIG_FILE": os.devnull,
        "AWS_SHARED_CREDENTIALS_FILE": os.devnull,
    }

    # stdin at EOF: the stdio server starts, finds no client and exits.
    result = subprocess.run(
        [sys.executable, "-m", module],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
        env=environment,
        check=False,
    )

    assert "Starting MCP server" in result.stderr  # it really started
    assert not [text for text in BANNER_TEXT if text in result.stderr], result.stderr
