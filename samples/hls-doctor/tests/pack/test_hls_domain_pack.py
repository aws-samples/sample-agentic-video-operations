"""The hls pack loads through the shared contract and matches the MCP surface."""

import asyncio
from pathlib import Path

from fastmcp import Client

from hls_doctor.domain_pack import create_domain_pack
from hls_doctor.entrypoints.serve_mcp import build_hls_doctor_server
from media_ops_contracts.domain_pack import DomainPack, load_domain_packs

FIXTURES_DIR = Path(__file__).resolve().parents[4] / "fixtures"


def test_entry_point_loads_the_pack_through_the_contract() -> None:
    [pack] = load_domain_packs(["hls"])
    assert isinstance(pack, DomainPack)
    assert pack.name == "hls"
    assert pack.write_tools() == []


def test_pack_tools_match_the_mcp_server_tools() -> None:
    pack = create_domain_pack()
    pack_names = {tool.__name__ for tool in pack.read_tools()}
    server = build_hls_doctor_server()

    async def server_names() -> set[str]:
        async with Client(server) as client:
            return {tool.name for tool in await client.list_tools()}

    assert pack_names == asyncio.run(server_names())


def test_fixture_scenarios_exist_on_disk() -> None:
    pack = create_domain_pack()
    for scenario in pack.fixture_scenarios:
        assert (FIXTURES_DIR / scenario / "http.exchanges.json").is_file()


def test_pack_skills_parse_when_present() -> None:
    pack = create_domain_pack()
    for path in pack.skill_paths:
        assert path.name == "SKILL.md" and path.read_text().strip()
