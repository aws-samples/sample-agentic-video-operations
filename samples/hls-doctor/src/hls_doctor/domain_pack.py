"""The HLS domain pack for the media operations hub. Read-only: no write tools."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from hls_doctor.settings.runtime_settings import load_hls_doctor_settings
from hls_doctor.tool_surface.create_inspection_tools import create_inspection_tools
from media_ops_contracts.domain_pack import ReadTool, WriteTool
from media_ops_contracts.read_utc_now import read_utc_now

SKILLS = Path(__file__).with_name("skills")


@dataclass(frozen=True)
class HlsPack:
    reads: list[ReadTool]
    name: str = "hls"
    skill_paths: list[Path] = field(default_factory=lambda: sorted(SKILLS.glob("*/SKILL.md")))
    fixture_scenarios: list[str] = field(default_factory=lambda: ["hls_clean_vod"])

    def read_tools(self) -> list[ReadTool]:
        return self.reads

    def write_tools(self) -> list[WriteTool]:
        return []


def create_domain_pack(*, clock: Callable[[], datetime] = read_utc_now) -> HlsPack:
    settings = load_hls_doctor_settings()
    return HlsPack(reads=create_inspection_tools(settings))
