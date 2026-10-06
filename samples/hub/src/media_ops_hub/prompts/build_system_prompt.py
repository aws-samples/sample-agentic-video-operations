"""The hub system prompt: behavior rules plus one line per loaded skill (extend_the_hub.md §3)."""

from pathlib import Path

from media_ops_contracts.skill_catalogue import SkillCatalogue

INSTRUCTIONS = Path(__file__).with_name("hub_instructions.md")
PROMPT_VERSION = "hub-v1"


def build_system_prompt(catalogue: SkillCatalogue) -> str:
    skills = "\n".join(catalogue.prompt_lines()) or "- none"
    return INSTRUCTIONS.read_text().replace("{skills}", skills)
