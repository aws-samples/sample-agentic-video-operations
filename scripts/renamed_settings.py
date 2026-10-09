"""Settings still set under their old HUB_* names, and what each became.

The deploy and the runtime read only the AGENTIC_IOPS_* names, so an old name is ignored and
fails open: HUB_WRITE_TAG drops the write tag scope, and HUB_JWT_* leaves IAM auth, where the
runtime trusts the caller-supplied actor header. `just deploy agentic-iops-streaming` refuses
while any is set; `just doctor` names them. The runtime keeps its own copy of this rule
(agentic_iops_streaming/settings/runtime_settings.py), tested to agree.
"""

from collections.abc import Mapping

OLD_PREFIX = "HUB_"
NEW_PREFIX = "AGENTIC_IOPS_"
# The nine settings this sample renamed. Only these: other HUB_* variables exist, such as the GitHub
# `hub` CLI's HUB_PROTOCOL, and are none of this sample's business.
RENAMED = frozenset(
    {
        "HUB_BEARER_TOKEN",
        "HUB_INVOKER_ROLE_NAME",
        "HUB_JWT_ALLOWED_CLIENTS",
        "HUB_JWT_CLIENT_IDS",
        "HUB_JWT_DISCOVERY_URL",
        "HUB_JWT_ISSUER",
        "HUB_LOCAL_MODE",
        "HUB_TOOL_BUDGET",
        "HUB_WRITE_TAG",
    }
)
CONSEQUENCES = {
    "HUB_WRITE_TAG": "writes would not be tag-scoped",
    "HUB_JWT_DISCOVERY_URL": (
        "the runtime would deploy with IAM auth and trust the caller-supplied actor header"
    ),
    "HUB_JWT_CLIENT_IDS": (
        "the runtime would deploy with IAM auth and trust the caller-supplied actor header"
    ),
}


def find_renamed_settings(environ: Mapping[str, str]) -> dict[str, str]:
    """Old name -> new name, for every HUB_* setting present (set beside its new name too)."""
    return {
        name: NEW_PREFIX + name.removeprefix(OLD_PREFIX)
        for name in sorted(environ)
        if name in RENAMED
    }


def describe_renames(found: Mapping[str, str]) -> str:
    return ", ".join(f"{old} -> {new}" for old, new in found.items())


def describe_consequences(found: Mapping[str, str]) -> list[str]:
    return sorted({CONSEQUENCES[old] for old in found if old in CONSEQUENCES})
