"""Every setting agentic-iops-streaming, its scripts and its README read is documented in
.env.example."""

import re
from pathlib import Path

from agentic_iops_streaming.settings.runtime_settings import AgenticIopsSettings

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = [
    ROOT / "scripts/manage_agentic_iops_streaming_stack.py",
    ROOT / "scripts/invoke_agentic_iops_streaming.py",
    ROOT
    / "samples/agentic-iops-streaming/src/agentic_iops_streaming/bootstrap"
    / "export_approval_signing_key.py",
]
ENV_KEY = r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+"


def documented_keys() -> set[str]:
    lines = (ROOT / ".env.example").read_text().splitlines()
    return {
        match.group(1)
        for line in lines
        if (match := re.match(rf"^#?\s*({ENV_KEY})=", line.strip()))
    }


def keys_the_agentic_iops_reads() -> set[str]:
    keys = {name.upper() for name in AgenticIopsSettings.model_fields}
    for script in SCRIPTS:
        keys |= set(re.findall(rf'environ\.get\("({ENV_KEY})"', script.read_text()))
    readme = (ROOT / "samples/agentic-iops-streaming/README.md").read_text()
    keys |= set(re.findall(rf"`({ENV_KEY})(?:=[^`]*)?`", readme))
    return keys


def test_every_key_the_agentic_iops_reads_is_in_env_example():
    missing = keys_the_agentic_iops_reads() - documented_keys()
    assert not missing, f"add to .env.example: {sorted(missing)}"


def test_the_invoker_role_key_the_readme_names_is_documented():
    assert "AGENTIC_IOPS_INVOKER_ROLE_NAME" in documented_keys()
