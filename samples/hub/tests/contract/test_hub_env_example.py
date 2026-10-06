"""Every setting the hub, its scripts and its README read is documented in .env.example."""

import re
from pathlib import Path

from media_ops_hub.settings.runtime_settings import HubSettings

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = [
    ROOT / "scripts/manage_hub_stack.py",
    ROOT / "scripts/invoke_hub.py",
    ROOT / "samples/hub/src/media_ops_hub/bootstrap/export_approval_signing_key.py",
]
ENV_KEY = r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+"


def documented_keys() -> set[str]:
    lines = (ROOT / ".env.example").read_text().splitlines()
    return {
        match.group(1)
        for line in lines
        if (match := re.match(rf"^#?\s*({ENV_KEY})=", line.strip()))
    }


def keys_the_hub_reads() -> set[str]:
    keys = {name.upper() for name in HubSettings.model_fields}
    for script in SCRIPTS:
        keys |= set(re.findall(rf'environ\.get\("({ENV_KEY})"', script.read_text()))
    readme = (ROOT / "samples/hub/README.md").read_text()
    keys |= set(re.findall(rf"`({ENV_KEY})(?:=[^`]*)?`", readme))
    return keys


def test_every_key_the_hub_reads_is_in_env_example():
    missing = keys_the_hub_reads() - documented_keys()
    assert not missing, f"add to .env.example: {sorted(missing)}"


def test_the_invoker_role_key_the_readme_names_is_documented():
    assert "HUB_INVOKER_ROLE_NAME" in documented_keys()
