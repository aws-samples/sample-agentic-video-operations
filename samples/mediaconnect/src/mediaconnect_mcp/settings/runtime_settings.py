"""Read MediaConnect runtime settings once from the process environment."""

from pathlib import Path

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from media_ops_contracts.resolve_demo_scenario import resolve_demo_scenario

DEFAULT_DEMO_SCENARIO = "srt_packet_loss"


class RuntimeSettings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    aws_region: str | None = None
    thumbnail_model_id: str | None = None
    mediaconnect_flow_arn: str | None = None
    allow_writes: bool = False
    demo: bool = False
    demo_scenario: str = DEFAULT_DEMO_SCENARIO
    fixtures_dir: Path = Path("fixtures")
    approval_signing_key: SecretStr = SecretStr("")
    # analyze_flow_visual_quality defaults (the hub sets 8 and 20); the tool blocks for the
    # whole window.
    visual_quality_frames: int = Field(default=10, ge=2, le=20)
    visual_quality_window_seconds: int = Field(default=30, ge=1, le=120)

    @field_validator("demo_scenario", mode="before")
    @classmethod
    def default_empty_scenario(cls, value: str | None) -> str:
        return resolve_demo_scenario(value, DEFAULT_DEMO_SCENARIO)

    @model_validator(mode="after")
    def require_runtime_values(self) -> "RuntimeSettings":
        required = {} if self.demo else {"AWS_REGION": self.aws_region}
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"Missing required setting(s): {', '.join(missing)}")
        return self


def load_runtime_settings() -> RuntimeSettings:
    return RuntimeSettings()
