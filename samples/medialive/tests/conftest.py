"""Keep medialive tests hermetic: `just` exports the root .env, which tests must not depend on."""

import pytest

ENV_SET_BY_THE_ROOT_DOTENV = (
    "AGENT_MODEL_ID",
    "THUMBNAIL_MODEL_ID",
    "DEMO",
    "DEMO_SCENARIO",
    "ALLOW_WRITES",
    "MEMORY_ID",
)


@pytest.fixture(autouse=True)
def clear_runtime_environment(monkeypatch):
    for name in ENV_SET_BY_THE_ROOT_DOTENV:
        monkeypatch.delenv(name, raising=False)
