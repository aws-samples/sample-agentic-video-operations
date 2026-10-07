"""Single source of truth for the Bedrock model IDs this repository uses.

Every other place a model ID appears (code defaults, CDK parameter defaults,
docs, .env examples) must use one of these values; `check_model_ids.py`
enforces it. Add a new ID here first, with the date you verified it against
https://docs.aws.amazon.com/bedrock/latest/userguide/models-supported.html.
"""

# Verified against the Bedrock model catalogue on 2026-10-06.
MAIN_AGENT_MODEL_ID = "us.anthropic.claude-sonnet-4-6"
VISION_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

# Variants of the same models for specific deployment shapes.
MAIN_AGENT_MODEL_ID_SINGLE_REGION = "anthropic.claude-sonnet-4-6"
# The foundation model behind VISION_MODEL_ID: agentic-iops-streaming's IAM grants it (derived in
# the stack).
VISION_MODEL_ID_SINGLE_REGION = "anthropic.claude-haiku-4-5-20251001-v1:0"
VISION_MODEL_ID_GLOBAL = "global.anthropic.claude-haiku-4-5-20251001-v1:0"

ALLOWED_MODEL_IDS = frozenset(
    {
        MAIN_AGENT_MODEL_ID,
        VISION_MODEL_ID,
        MAIN_AGENT_MODEL_ID_SINGLE_REGION,
        VISION_MODEL_ID_SINGLE_REGION,
        VISION_MODEL_ID_GLOBAL,
    }
)
