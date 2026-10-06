"""Validated hub settings (build_a_sample.md §5). Read once at startup."""

from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class HubSettings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    aws_region: str = Field(default="us-west-2")
    agent_model_id: str | None = Field(default=None)
    media_domains: str = Field(default="medialive,mediaconnect")
    allow_writes: bool = Field(default=False)
    memory_id: str = Field(default="")
    approval_signing_key: str = Field(default="")
    hub_tool_budget: int = Field(default=12, ge=1)
    session_dir: Path = Field(default=Path(".hub-sessions"))
    # Only `just run hub` sets this. It lets a request without an actor header or session id
    # run as one local operator; everywhere else such a request is refused.
    hub_local_mode: bool = Field(default=False)

    @model_validator(mode="after")
    def require_a_shared_key_with_shared_sessions(self) -> "HubSettings":
        """With AgentCore Memory, a run may resume in another container: approvals signed
        before the pause must verify there too, so the key cannot be per process."""
        if self.memory_id and not self.approval_signing_key:
            raise ValueError("MEMORY_ID is set, so APPROVAL_SIGNING_KEY must be set as well.")
        return self


def load_hub_settings() -> HubSettings:
    return HubSettings()
