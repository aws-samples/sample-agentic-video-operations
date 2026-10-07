"""Read one SKILL.md: front-matter metadata, plus the body on demand
(extend_agentic_iops_streaming.md §3)."""

import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

_FRONT_MATTER = re.compile(r"\A---\n(?P<header>.*?)\n---\n(?P<body>.*)\Z", re.DOTALL)
_LINE = re.compile(r"^(?P<key>[a-z_]+):\s*(?P<value>.*?)\s*$")


class SkillMetadata(BaseModel):
    """What the system prompt shows about a skill; the body is loaded only on request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    description: str = Field(min_length=1, max_length=300)
    domain: str = Field(pattern=r"^[a-z0-9]+$")


class Skill(BaseModel):
    model_config = ConfigDict(frozen=True)

    metadata: SkillMetadata
    body: str
    path: Path


class SkillError(ValueError):
    """A SKILL.md that the coordinator must refuse at startup."""


def parse_skill(path: Path) -> Skill:
    """Parse `<name>/SKILL.md`. The front-matter `name` must equal the directory name."""
    text = path.read_text(encoding="utf-8")
    match = _FRONT_MATTER.match(text)
    if not match:
        raise SkillError(f"{path}: missing '---' front-matter block")
    fields = _parse_header(path, match["header"])
    try:
        metadata = SkillMetadata(**fields)
    except ValidationError as error:
        raise SkillError(f"{path}: invalid front-matter: {error.errors()[0]['msg']}") from error
    if metadata.name != path.parent.name:
        raise SkillError(f"{path}: name '{metadata.name}' must equal its directory name")
    body = match["body"].strip()
    if not body:
        raise SkillError(f"{path}: empty body")
    return Skill(metadata=metadata, body=body, path=path)


def _parse_header(path: Path, header: str) -> dict[str, str]:
    """Plain `key: value` lines only; a repeated key is an error, never "last one wins"."""
    fields: dict[str, str] = {}
    for line in header.splitlines():
        if not line.strip():
            continue
        found = _LINE.match(line)
        if not found:
            raise SkillError(f"{path}: front-matter line is not 'key: value': {line!r}")
        key, value = found["key"], found["value"].strip("\"'")
        if key in fields:
            raise SkillError(f"{path}: front-matter key '{key}' appears twice")
        fields[key] = value
    return fields
