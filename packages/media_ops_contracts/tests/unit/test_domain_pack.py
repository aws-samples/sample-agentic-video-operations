import textwrap
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from pydantic import BaseModel

from media_ops_contracts import domain_pack
from media_ops_contracts.action_result import ActionResult
from media_ops_contracts.approved_action import ApprovedAction
from media_ops_contracts.domain_pack import (
    DomainPack,
    DomainPackError,
    WriteTool,
    load_domain_packs,
    parse_domain_names,
)


class Channel(BaseModel):
    channel_id: str


def describe_channel(channel_id: str) -> Channel:
    return Channel(channel_id=channel_id)


def list_channels() -> list[Channel]:
    return []


def stop_channel(channel_id: str, approved_action: ApprovedAction) -> ActionResult:
    raise NotImplementedError


def untyped_stop(channel_id: str, approved_action: str) -> str:
    return channel_id


def stop_returning_text(channel_id: str, approved_action: ApprovedAction) -> str:
    return channel_id


def read_returning_dict(channel_id: str) -> dict:
    return {}


@dataclass
class FakePack:
    name: str
    skill_paths: list[Path] = field(default_factory=list)
    fixture_scenarios: list[str] = field(default_factory=lambda: ["input_loss"])

    read: list = field(default_factory=lambda: [describe_channel, list_channels])
    write: list = field(
        default_factory=lambda: [WriteTool(function=stop_channel, resource_parameter="channel_id")]
    )

    def read_tools(self):
        return self.read

    def write_tools(self):
        return self.write


def factories(*names):
    return {name: (lambda name=name: FakePack(name)) for name in names}


def test_a_fake_pack_satisfies_the_protocol():
    assert isinstance(FakePack("medialive"), DomainPack)


@pytest.mark.parametrize(
    ("value", "names"),
    [
        ("medialive,mediaconnect", ["medialive", "mediaconnect"]),
        (" medialive , , mediaconnect,medialive ", ["medialive", "mediaconnect"]),
        ("", []),
    ],
)
def test_media_domains_parsing_keeps_order_and_drops_blanks_and_repeats(value, names):
    assert parse_domain_names(value) == names


def test_selected_packs_load_in_the_requested_order():
    packs = load_domain_packs(["mediaconnect", "medialive"], factories("medialive", "mediaconnect"))
    assert [pack.name for pack in packs] == ["mediaconnect", "medialive"]


def test_an_unknown_pack_fails_and_lists_the_installed_ones():
    with pytest.raises(DomainPackError) as error:
        load_domain_packs(["medialive", "cmcd"], factories("medialive", "mediaconnect"))
    assert "Unknown domain pack(s): cmcd" in str(error.value)
    assert "Installed packs: mediaconnect, medialive" in str(error.value)


def test_an_empty_selection_fails():
    with pytest.raises(DomainPackError, match="MEDIA_DOMAINS is empty"):
        load_domain_packs([], factories("medialive"))


def test_a_pack_registered_under_another_name_is_refused():
    with pytest.raises(DomainPackError, match="returned a pack named mediaconnect"):
        load_domain_packs(["medialive"], {"medialive": lambda: FakePack("mediaconnect")})


def test_an_entry_point_that_does_not_return_a_pack_is_refused():
    with pytest.raises(DomainPackError, match="did not return a DomainPack"):
        load_domain_packs(["medialive"], {"medialive": lambda: object()})


def test_write_tools_must_take_approved_action_and_name_their_resource():
    with pytest.raises(ValueError, match="approved_action"):
        WriteTool(function=describe_channel, resource_parameter="channel_id")
    with pytest.raises(ValueError, match="flow_arn"):
        WriteTool(function=stop_channel, resource_parameter="flow_arn")


def test_a_write_tool_with_an_untyped_approval_is_refused():
    with pytest.raises(ValueError, match="approved_action must be typed ApprovedAction"):
        WriteTool(function=untyped_stop, resource_parameter="channel_id")


def test_a_write_tool_that_does_not_return_an_action_result_is_refused():
    with pytest.raises(ValueError, match="must return ActionResult"):
        WriteTool(function=stop_returning_text, resource_parameter="channel_id")


def test_a_read_tool_without_a_pydantic_return_type_is_refused_at_load():
    bad = {"medialive": lambda: FakePack("medialive", read=[read_returning_dict])}
    with pytest.raises(DomainPackError, match="read tool read_returning_dict must return"):
        load_domain_packs(["medialive"], bad)


def test_write_tools_must_be_write_tool_descriptors():
    bad = {"medialive": lambda: FakePack("medialive", write=[stop_channel])}
    with pytest.raises(DomainPackError, match="must be a WriteTool"):
        load_domain_packs(["medialive"], bad)


def test_packs_are_discovered_through_the_entry_point_group(tmp_path, monkeypatch):
    module = tmp_path / "fake_media_pack.py"
    module.write_text(
        textwrap.dedent(
            """
            from dataclasses import dataclass, field

            @dataclass
            class Pack:
                name: str = "fakelive"
                skill_paths: list = field(default_factory=list)
                fixture_scenarios: list = field(default_factory=list)

                def read_tools(self):
                    return []

                def write_tools(self):
                    return []

            def create_domain_pack():
                return Pack()
            """
        )
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    from importlib.metadata import EntryPoint

    group = domain_pack.ENTRY_POINT_GROUP
    point = EntryPoint("fakelive", "fake_media_pack:create_domain_pack", group)
    monkeypatch.setattr(domain_pack, "entry_points", lambda group: [point])
    [pack] = load_domain_packs(["fakelive"])
    assert pack.name == "fakelive"
