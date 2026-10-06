"""The MediaConnect domain pack for the media operations hub."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from media_ops_contracts.domain_pack import ReadTool, WriteTool
from media_ops_contracts.read_utc_now import read_utc_now
from mediaconnect_mcp.bootstrap.create_mediaconnect_clients import (
    create_mediaconnect_clients,
)
from mediaconnect_mcp.settings.runtime_settings import load_runtime_settings
from mediaconnect_mcp.tool_surface.create_read_tools import create_read_tools
from mediaconnect_mcp.tool_surface.create_write_tools import create_write_tools

SKILLS = Path(__file__).with_name("skills")


@dataclass(frozen=True)
class MediaConnectPack:
    reads: list[ReadTool]
    writes: list[WriteTool]
    name: str = "mediaconnect"
    skill_paths: list[Path] = field(default_factory=lambda: sorted(SKILLS.glob("*/SKILL.md")))
    fixture_scenarios: list[str] = field(default_factory=lambda: ["srt_packet_loss"])

    def read_tools(self) -> list[ReadTool]:
        return self.reads

    def write_tools(self) -> list[WriteTool]:
        return self.writes


def create_domain_pack(*, clock: Callable[[], datetime] = read_utc_now) -> MediaConnectPack:
    settings = load_runtime_settings()
    clients = create_mediaconnect_clients(settings)
    return MediaConnectPack(
        reads=create_read_tools(settings, clients),
        writes=create_write_tools(settings, clients, clock=clock),
    )
