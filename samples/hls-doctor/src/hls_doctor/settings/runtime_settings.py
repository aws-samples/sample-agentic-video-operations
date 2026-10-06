"""Validated HLS Doctor settings (build_a_sample.md §5). Read once at startup."""

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from media_ops_contracts.resolve_demo_scenario import resolve_demo_scenario

DEFAULT_DEMO_SCENARIO = "hls_segment_race"


class HlsDoctorSettings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    demo: bool = Field(default=False)
    demo_scenario: str = Field(default=DEFAULT_DEMO_SCENARIO)
    fixtures_dir: Path = Field(default=Path("fixtures"))
    hls_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    hls_user_agent: str = Field(default="hls-doctor/0.1")
    hls_max_watch_seconds: int = Field(default=60, ge=1, le=600)
    # Allows loopback/private fetch targets for diagnosing a local stream.
    # The guard refuses it inside the deployed container (DOCKER_CONTAINER=1).
    hls_allow_private_targets: bool = Field(default=False)

    @field_validator("demo_scenario", mode="before")
    @classmethod
    def default_scenario_when_empty(cls, value: str | None) -> str:
        return resolve_demo_scenario(value, DEFAULT_DEMO_SCENARIO)


def load_hls_doctor_settings() -> HlsDoctorSettings:
    return HlsDoctorSettings()
