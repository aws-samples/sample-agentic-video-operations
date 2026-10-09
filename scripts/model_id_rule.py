"""The Bedrock model-id rule, shared with both CDK stacks through model_id_rule.json.

The deploy scripts check AGENT_MODEL_ID and THUMBNAIL_MODEL_ID with it before anything is
installed, built or diffed, so a bad id fails in seconds instead of at CloudFormation's
parameter check after the image build. The stacks enforce the same rule at synth or deploy.
"""

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

RULE = json.loads((Path(__file__).resolve().parent / "model_id_rule.json").read_text())
PROFILE_PREFIXES: tuple[str, ...] = tuple(RULE["profile_prefixes"])
MODEL_ID_PATTERN = re.compile(RULE["pattern"])


def find_invalid_model_ids(settings: Mapping[str, str], names: Sequence[str]) -> list[str]:
    """One message per set model id that isn't a model or cross-Region profile id."""
    return [
        f"{name}={settings[name]!r} is not a Bedrock model id (provider.model) or a "
        f"cross-Region profile id ({PROFILE_PREFIXES[0]}.provider.model)."
        for name in names
        if settings.get(name) and not MODEL_ID_PATTERN.fullmatch(settings[name])
    ]
