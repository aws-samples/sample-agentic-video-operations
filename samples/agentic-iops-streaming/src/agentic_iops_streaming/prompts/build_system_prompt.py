"""The agent's system prompt: behavior rules plus one line per loaded skill
(extend_agentic_iops_streaming.md §3)."""

from pathlib import Path

from media_ops_contracts.skill_catalogue import SkillCatalogue

INSTRUCTIONS = Path(__file__).with_name("agentic_iops_instructions.md")
PROMPT_VERSION = "agentic-iops-v1"


def build_system_prompt(catalogue: SkillCatalogue) -> str:
    skills = "\n".join(catalogue.prompt_lines()) or "- none"
    return INSTRUCTIONS.read_text().replace("{skills}", skills)
