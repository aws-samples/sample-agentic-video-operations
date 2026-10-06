"""Pluggable media domains for the hub (extend_the_hub.md §2). Framework-free.

A sample package exports `create_domain_pack() -> DomainPack` under the entry-point
group `media_ops.domain_packs`; `MEDIA_DOMAINS` selects which packs the hub loads.
"""

import inspect
import typing
from collections.abc import Callable, Iterable, Mapping, Sequence
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, model_validator

from media_ops_contracts.action_result import ActionResult
from media_ops_contracts.approved_action import ApprovedAction

ENTRY_POINT_GROUP = "media_ops.domain_packs"

ReadTool = Callable[..., BaseModel | Sequence[BaseModel]]
"""A typed read function returning a pydantic model or a list of them."""

WriteFunction = Callable[..., ActionResult]
"""A typed write function taking `approved_action: ApprovedAction`."""


class WriteTool(BaseModel):
    """A typed write function plus the input that names the resource it changes."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    function: WriteFunction
    resource_parameter: str

    @model_validator(mode="after")
    def check_signature(self) -> "WriteTool":
        name = getattr(self.function, "__name__", repr(self.function))
        parameters = inspect.signature(self.function).parameters
        missing = {self.resource_parameter, "approved_action"} - set(parameters)
        if missing:
            raise ValueError(f"write tool {name} lacks parameter(s): {', '.join(sorted(missing))}")
        hints = typing.get_type_hints(self.function)
        if hints.get("approved_action") is not ApprovedAction:
            raise ValueError(f"write tool {name}: approved_action must be typed ApprovedAction")
        if not _is_subclass(hints.get("return"), ActionResult):
            raise ValueError(f"write tool {name} must return ActionResult")
        return self


@runtime_checkable
class DomainPack(Protocol):
    name: str
    skill_paths: Sequence[Path]
    fixture_scenarios: Sequence[str]

    def read_tools(self) -> Sequence[ReadTool]: ...

    def write_tools(self) -> Sequence[WriteTool]: ...


class DomainPackError(ValueError):
    """MEDIA_DOMAINS names a pack that is not installed, or a pack is malformed."""


def parse_domain_names(media_domains: str) -> list[str]:
    """`"medialive, mediaconnect"` -> `["medialive", "mediaconnect"]`, order kept, no repeats."""
    names = [name.strip() for name in media_domains.split(",") if name.strip()]
    return list(dict.fromkeys(names))


def installed_pack_factories() -> dict[str, Callable[[], DomainPack]]:
    """Every pack registered under the entry-point group: name -> create the pack."""
    return {
        point.name: (lambda point=point: point.load()())
        for point in entry_points(group=ENTRY_POINT_GROUP)
    }


def load_domain_packs(
    names: Iterable[str], factories: Mapping[str, Callable[[], Any]] | None = None
) -> list[DomainPack]:
    """Create the named packs in order. Fails at startup, listing what is installed."""
    available = installed_pack_factories() if factories is None else factories
    wanted = list(names)
    if not wanted:
        raise DomainPackError(f"MEDIA_DOMAINS is empty. Installed packs: {_list(available)}.")
    unknown = [name for name in wanted if name not in available]
    if unknown:
        raise DomainPackError(
            f"Unknown domain pack(s): {', '.join(unknown)}. Installed packs: {_list(available)}."
        )
    return [_create_pack(name, available[name]) for name in wanted]


def _create_pack(name: str, factory: Callable[[], Any]) -> DomainPack:
    pack = factory()
    if not isinstance(pack, DomainPack):
        raise DomainPackError(f"Entry point {name} did not return a DomainPack.")
    if pack.name != name:
        raise DomainPackError(f"Entry point {name} returned a pack named {pack.name}.")
    for tool in pack.read_tools():
        check_read_tool(tool)
    if not all(isinstance(tool, WriteTool) for tool in pack.write_tools()):
        raise DomainPackError(f"Pack {name}: every write tool must be a WriteTool.")
    return pack


def check_read_tool(function: Callable[..., Any]) -> None:
    """A read tool must declare a pydantic model, or a list of them, as its return type."""
    name = getattr(function, "__name__", repr(function))
    returned = typing.get_type_hints(function).get("return")
    item = (
        typing.get_args(returned)[0]
        if typing.get_origin(returned) in (list, Sequence)
        else returned
    )
    if not _is_subclass(item, BaseModel):
        raise DomainPackError(f"read tool {name} must return a pydantic model or a list of them")


def _is_subclass(candidate: Any, parent: type) -> bool:
    return isinstance(candidate, type) and issubclass(candidate, parent)


def _list(available: Mapping[str, Any]) -> str:
    return ", ".join(sorted(available)) or "none"
