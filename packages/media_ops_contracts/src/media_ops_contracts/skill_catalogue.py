"""All skills the hub loaded: metadata for the prompt, bodies on demand (extend_the_hub.md §3)."""

from collections.abc import Iterable
from pathlib import Path

from media_ops_contracts.parse_skill import Skill, SkillError, parse_skill


class SkillCatalogue:
    def __init__(self, skills: Iterable[Skill]) -> None:
        self._skills: dict[str, Skill] = {}
        for skill in skills:
            name = skill.metadata.name
            if name in self._skills:
                raise SkillError(
                    f"skill '{name}' is defined twice: {self._skills[name].path} and {skill.path}"
                )
            self._skills[name] = skill

    @classmethod
    def from_paths(cls, paths: Iterable[Path]) -> "SkillCatalogue":
        """Parse every SKILL.md up front, so a broken skill stops startup, not a request."""
        return cls(parse_skill(path) for path in paths)

    def names(self) -> list[str]:
        return sorted(self._skills)

    def prompt_lines(self) -> list[str]:
        """One line per skill for the system prompt: name and description only."""
        return [
            f"- {skill.metadata.name}: {skill.metadata.description}"
            for skill in sorted(self._skills.values(), key=lambda s: s.metadata.name)
        ]

    def load_body(self, name: str) -> str:
        """The skill body, or the list of names when `name` is unknown."""
        skill = self._skills.get(name)
        if skill is None:
            return f"Unknown skill '{name}'. Available skills: {', '.join(self.names()) or 'none'}."
        return skill.body
