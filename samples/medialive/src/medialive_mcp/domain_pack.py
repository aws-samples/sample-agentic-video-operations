"""The medialive domain pack for the coordinator (extend_agentic_iops_streaming.md §2).

The pack wraps the same typed functions the MCP server registers, and builds its own
settings and clients (DEMO replay included). It never imports Strands or the coordinator.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from media_ops_contracts.domain_pack import ReadTool, WriteTool
from media_ops_contracts.read_utc_now import read_utc_now
from medialive_mcp.bootstrap.create_medialive_clients import create_medialive_clients
from medialive_mcp.settings.runtime_settings import load_runtime_settings
from medialive_mcp.tool_surface.create_read_tools import create_read_tools
from medialive_mcp.tool_surface.create_write_tools import create_write_tools

SKILLS = Path(__file__).with_name("skills")


@dataclass(frozen=True)
class MediaLivePack:
    reads: list[ReadTool]
    writes: list[WriteTool]
    name: str = "medialive"
    skill_paths: list[Path] = field(default_factory=lambda: sorted(SKILLS.glob("*/SKILL.md")))
    fixture_scenarios: list[str] = field(
        default_factory=lambda: ["input_loss", "no_input", "srt_packet_loss"]
    )

    def read_tools(self) -> list[ReadTool]:
        return self.reads

    def write_tools(self) -> list[WriteTool]:
        """All write tools; the coordinator registers them only with ALLOW_WRITES=true."""
        return self.writes


def create_domain_pack(*, clock: Callable[[], datetime] = read_utc_now) -> MediaLivePack:
    settings = load_runtime_settings()
    clients = create_medialive_clients(settings)
    return MediaLivePack(
        reads=create_read_tools(settings, clients),
        writes=create_write_tools(settings, clients, clock=clock),
    )
