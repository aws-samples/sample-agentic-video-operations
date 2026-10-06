import json
import textwrap
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_PLACEHOLDER = "/absolute/path/to/sample-agentic-video-operations"
SAMPLES = {
    "cmcd": ("cmcd-mcp-server", "serve-cmcd", "cmcd_rebuffering"),
    "mediaconnect": (
        "mediaconnect-mcp-server",
        "serve-mediaconnect",
        "srt_packet_loss",
    ),
    "medialive": ("medialive-mcp-server", "serve-medialive", "input_loss"),
    "hls-doctor": ("hls-doctor", "serve-hls-doctor", "hls_segment_race"),
}


def load_servers(sample: str) -> dict:
    path = REPOSITORY_ROOT / "samples" / sample / "mcp.json"
    return json.loads(path.read_text())["mcpServers"]


def read_json_blocks(path: Path) -> list[dict]:
    blocks = []
    lines = path.read_text().splitlines()
    index = 0
    while index < len(lines):
        if lines[index].strip() != "```json":
            index += 1
            continue
        end = index + 1
        while lines[end].strip() != "```":
            end += 1
        blocks.append(json.loads(textwrap.dedent("\n".join(lines[index + 1 : end]))))
        index = end + 1
    return blocks


@pytest.mark.parametrize(("sample", "details"), SAMPLES.items())
def test_demo_entries_are_hermetic(sample, details):
    distribution, command, scenario = details
    demo = load_servers(sample)[f"{sample}-demo"]

    assert demo["args"] == [
        "run",
        "--directory",
        REPOSITORY_PLACEHOLDER,
        "--package",
        distribution,
        command,
    ]
    assert demo["env"] == {
        "DEMO": "1",
        "DEMO_SCENARIO": scenario,
        "ALLOW_WRITES": "false",
    }


@pytest.mark.parametrize(("sample", "details"), SAMPLES.items())
def test_live_entries_load_the_root_env(sample, details):
    distribution, command, _scenario = details
    live = load_servers(sample)[sample]

    assert live["args"] == [
        "run",
        "--directory",
        REPOSITORY_PLACEHOLDER,
        "--env-file",
        ".env",
        "--package",
        distribution,
        command,
    ]
    assert "env" not in live


@pytest.mark.parametrize("sample", SAMPLES)
def test_readme_embeds_the_committed_mcp_configuration(sample):
    servers = load_servers(sample)
    readme = REPOSITORY_ROOT / "samples" / sample / "README.md"

    assert {"mcpServers": servers} in read_json_blocks(readme)
