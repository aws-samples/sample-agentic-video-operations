"""Read validated Hydrolix agent settings once per process."""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RuntimeSettings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra="ignore",
        validate_default=True,
    )

    agent_model_id: str = ""

    @field_validator("agent_model_id")
    @classmethod
    def require_agent_model(cls, value: str) -> str:
        model_id = value.strip()
        if not model_id:
            raise ValueError("Missing required setting(s): AGENT_MODEL_ID")
        return model_id


@lru_cache
def load_runtime_settings() -> RuntimeSettings:
    return RuntimeSettings()
