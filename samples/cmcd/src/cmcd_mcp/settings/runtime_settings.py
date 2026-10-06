"""Read CMCD runtime settings once from the process environment."""

from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from media_ops_contracts.resolve_demo_scenario import resolve_demo_scenario

DEFAULT_DEMO_SCENARIO = "cmcd_rebuffering"


class RuntimeSettings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    influxdb_url: str | None = None
    influxdb_token: str | None = None
    influxdb_org: str | None = None
    verify_ssl: bool = True
    demo: bool = False
    demo_scenario: str = DEFAULT_DEMO_SCENARIO
    fixtures_dir: Path = Path("fixtures")

    @field_validator("demo_scenario", mode="before")
    @classmethod
    def default_empty_scenario(cls, value: str | None) -> str:
        return resolve_demo_scenario(value, DEFAULT_DEMO_SCENARIO)

    @model_validator(mode="after")
    def require_live_connection(self) -> "RuntimeSettings":
        if self.demo:
            return self
        required = {
            "INFLUXDB_URL": self.influxdb_url,
            "INFLUXDB_TOKEN": self.influxdb_token,
            "INFLUXDB_ORG": self.influxdb_org,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"Missing required setting(s): {', '.join(missing)}")
        return self
