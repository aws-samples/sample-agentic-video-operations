"""Read MediaConnect runtime settings once from the process environment."""

from pathlib import Path

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_THUMBNAIL_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"


class RuntimeSettings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    aws_region: str | None = None
    thumbnail_model_id: str = DEFAULT_THUMBNAIL_MODEL_ID
    mediaconnect_flow_arn: str | None = None
    allow_writes: bool = False
    demo: bool = False
    demo_scenario: str = "srt_packet_loss"
    fixtures_dir: Path = Path("fixtures")
    approval_signing_key: SecretStr = SecretStr("")

    @model_validator(mode="after")
    def require_runtime_values(self) -> "RuntimeSettings":
        required = {} if self.demo else {"AWS_REGION": self.aws_region}
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"Missing required setting(s): {', '.join(missing)}")
        return self
