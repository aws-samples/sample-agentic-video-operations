"""Validated settings for the medialive sample (build_a_sample.md §5). Read once at startup."""

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings

from media_ops_contracts.resolve_demo_scenario import resolve_demo_scenario

DEFAULT_DEMO_SCENARIO = "input_loss"


class RuntimeSettings(BaseSettings):
    aws_region: str = Field(default="us-west-2")
    # Model ids come only from the root .env (build_a_sample.md §5); no fallback ids in code.
    agent_model_id: str | None = Field(default=None)
    thumbnail_model_id: str | None = Field(default=None)
    memory_id: str = Field(default="")
    medialive_channel_id: str = Field(default="")
    allow_writes: bool = Field(default=False)
    enable_code_mode: bool = Field(default=False)
    demo: bool = Field(default=False)
    demo_scenario: str = Field(default=DEFAULT_DEMO_SCENARIO)
    fixtures_dir: Path = Field(default=Path("fixtures"))
    # Empty means one random key per process (resolve_approval_signing_key); a deployment
    # injects a shared secret.
    approval_signing_key: str = Field(default="")

    @field_validator("demo_scenario", mode="before")
    @classmethod
    def default_empty_scenario(cls, value: str | None) -> str:
        return resolve_demo_scenario(value, DEFAULT_DEMO_SCENARIO)


def load_runtime_settings() -> RuntimeSettings:
    return RuntimeSettings()
