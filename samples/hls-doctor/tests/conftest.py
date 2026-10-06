"""Hermetic test setup: tests never depend on the root .env that `just` exports."""

from pathlib import Path

import pytest

from hls_doctor.settings.runtime_settings import HlsDoctorSettings

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_DIR = REPOSITORY_ROOT / "fixtures"

ENV_SET_BY_THE_ROOT_DOTENV = (
    "DEMO",
    "DEMO_SCENARIO",
    "FIXTURES_DIR",
    "ALLOW_WRITES",
    "HLS_TIMEOUT_SECONDS",
    "HLS_USER_AGENT",
    "HLS_MAX_WATCH_SECONDS",
)


@pytest.fixture(autouse=True)
def clear_runtime_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_SET_BY_THE_ROOT_DOTENV:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def demo_settings() -> "DemoSettingsFactory":
    return DemoSettingsFactory()


class DemoSettingsFactory:
    def __call__(self, scenario: str) -> HlsDoctorSettings:
        return HlsDoctorSettings(demo=True, demo_scenario=scenario, fixtures_dir=FIXTURES_DIR)
