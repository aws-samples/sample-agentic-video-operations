"""Validated settings for the medialive sample (build_a_sample.md §5). Read once at startup."""

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings

from media_ops_contracts.resolve_demo_scenario import resolve_demo_scenario

DEFAULT_DEMO_SCENARIO = "input_loss"


class RuntimeSettings(BaseSettings):
    aws_region: str = Field(default="us-west-2")
    thumbnail_model_id: str | None = Field(default=None)
    medialive_channel_id: str = Field(default="")
    allow_writes: bool = Field(default=False)
    demo: bool = Field(default=False)
    demo_scenario: str = Field(default=DEFAULT_DEMO_SCENARIO)
    fixtures_dir: Path = Field(default=Path("fixtures"))
    # Empty means one random key per process (resolve_approval_signing_key); a deployment
    # injects a shared secret.
    approval_signing_key: str = Field(default="")
    # analyze_channel_visual_quality defaults; the tool blocks for the whole window.
    visual_quality_frames: int = Field(default=10, ge=2, le=20)
    visual_quality_window_seconds: int = Field(default=30, ge=2, le=120)

    @field_validator("demo_scenario", mode="before")
    @classmethod
    def default_empty_scenario(cls, value: str | None) -> str:
        return resolve_demo_scenario(value, DEFAULT_DEMO_SCENARIO)


def load_runtime_settings() -> RuntimeSettings:
    return RuntimeSettings()
