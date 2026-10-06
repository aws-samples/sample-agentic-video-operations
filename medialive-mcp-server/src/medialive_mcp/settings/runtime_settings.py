"""Validated settings for the medialive sample (sample-contract §5). Read once at startup."""

import secrets
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings

DEFAULT_DEMO_SCENARIO = "input_loss"


class RuntimeSettings(BaseSettings):
    aws_region: str = Field(default="us-west-2")
    # Model ids come only from the root .env (sample-contract §5); no fallback ids in code.
    agent_model_id: str | None = Field(default=None)
    thumbnail_model_id: str | None = Field(default=None)
    memory_id: str = Field(default="")
    medialive_channel_id: str = Field(default="")
    allow_writes: bool = Field(default=False)
    enable_code_mode: bool = Field(default=False)
    demo: bool = Field(default=False)
    demo_scenario: str = Field(default="")
    fixtures_dir: Path = Field(default=Path("fixtures"))
    # Local MCP runs sign their own approvals; a deployment injects a shared secret.
    approval_signing_key: str = Field(default_factory=lambda: secrets.token_hex(32))

    @property
    def replay_scenario(self) -> str | None:
        """The fixture scenario to replay, or None to call AWS."""
        return (self.demo_scenario or DEFAULT_DEMO_SCENARIO) if self.demo else None


def load_runtime_settings() -> RuntimeSettings:
    return RuntimeSettings()
