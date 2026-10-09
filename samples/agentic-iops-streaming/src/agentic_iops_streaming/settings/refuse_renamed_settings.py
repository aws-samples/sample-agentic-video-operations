"""The runtime refuses to start while a setting still has its old HUB_* name.

An old name is ignored, which fails open: HUB_LOCAL_MODE or HUB_JWT_* changes who the runtime
believes the caller is. The same rule as scripts/renamed_settings.py, which the deploy uses.
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


def refuse_renamed_settings(environ: Mapping[str, str]) -> None:
    found = {
        name: NEW_PREFIX + name.removeprefix(OLD_PREFIX)
        for name in sorted(environ)
        if name in RENAMED
    }
    if found:
        renames = ", ".join(f"{old} -> {new}" for old, new in found.items())
        raise ValueError(
            f"Settings still use their old HUB_* names, which are ignored: rename {renames}."
        )
