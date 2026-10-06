"""One resource in the presentation graph (spec §6C)."""

from typing import Literal

from pydantic import BaseModel, Field

NodeType = Literal[
    "multivariant",
    "media_playlist",
    "segment",
    "part",
    "init_section",
    "key",
    "steering_manifest",
    "interstitial_asset_list",
]

NodeRole = Literal["video", "audio", "subtitles", "closed-captions", "iframe", "entry"]


class PresentationNode(BaseModel):
    url: str
    node_type: NodeType
    role: NodeRole | None = None
    parent_url: str | None = None
    declared_at_line: int | None = None
    group_id: str | None = None
    name: str | None = None
    language: str | None = None
    bandwidth: int | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    finding_ids: list[str] = Field(default_factory=list)
