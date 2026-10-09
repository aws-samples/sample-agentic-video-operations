"""Keep agentic-iops-streaming tests hermetic: `just` exports the root .env, which tests must not
depend on.

A MEMORY_ID leaking in would point the session manager at AgentCore Memory.
"""

import pytest

ENV_SET_BY_THE_ROOT_DOTENV = (
    "AGENT_MODEL_ID",
    "THUMBNAIL_MODEL_ID",
    "DEMO",
    "DEMO_SCENARIO",
    "FIXTURES_DIR",
    "ALLOW_WRITES",
    "MEMORY_ID",
    "APPROVAL_SIGNING_KEY",
    "MEDIA_DOMAINS",
    "AGENTIC_IOPS_TOOL_BUDGET",
    "AGENTIC_IOPS_PORT",
    "SESSION_DIR",
    "AGENTIC_IOPS_LOCAL_MODE",
    "AGENTIC_IOPS_JWT_ISSUER",
    "AGENTIC_IOPS_JWT_ALLOWED_CLIENTS",
)


@pytest.fixture(autouse=True)
def clear_runtime_environment(monkeypatch):
    for name in ENV_SET_BY_THE_ROOT_DOTENV:
        monkeypatch.delenv(name, raising=False)
