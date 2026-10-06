import pytest

from media_ops_contracts.parse_skill import SkillError, parse_skill
from media_ops_contracts.skill_catalogue import SkillCatalogue

GOOD = """---
name: diagnose-input-loss
description: When a channel shows input loss or slate, find whether the fault is upstream.
domain: medialive
---
1. Call check_channel_issues.
2. Read the logs for the failing pipeline.
"""


def write_skill(root, directory, text):
    path = root / directory / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(text)
    return path


def test_parses_metadata_and_body(tmp_path):
    skill = parse_skill(write_skill(tmp_path, "diagnose-input-loss", GOOD))
    assert skill.metadata.name == "diagnose-input-loss"
    assert skill.metadata.domain == "medialive"
    assert skill.body.startswith("1. Call check_channel_issues.")


def test_name_must_equal_the_directory(tmp_path):
    with pytest.raises(SkillError, match="must equal its directory name"):
        parse_skill(write_skill(tmp_path, "other-name", GOOD))


def test_a_repeated_key_is_an_error_not_last_one_wins(tmp_path):
    text = GOOD.replace("domain: medialive", "domain: medialive\nname: something-else")
    with pytest.raises(SkillError, match="appears twice"):
        parse_skill(write_skill(tmp_path, "diagnose-input-loss", text))


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("no front matter\n", "missing '---' front-matter"),
        (GOOD.replace("domain: medialive\n", ""), "invalid front-matter"),
        (GOOD.replace("domain: medialive", "domain: medialive\nowner: me"), "invalid front-matter"),
        (GOOD.replace("name: diagnose-input-loss", "name: Diagnose Input"), "invalid front-matter"),
        (GOOD.split("---\n1.")[0] + "---\n", "empty body"),
    ],
)
def test_malformed_skills_are_refused(tmp_path, text, message):
    with pytest.raises(SkillError, match=message):
        parse_skill(write_skill(tmp_path, "diagnose-input-loss", text))


def test_catalogue_shows_metadata_and_loads_bodies_on_demand(tmp_path):
    catalogue = SkillCatalogue.from_paths([write_skill(tmp_path, "diagnose-input-loss", GOOD)])
    assert catalogue.prompt_lines() == [
        "- diagnose-input-loss: When a channel shows input loss or slate, find whether the "
        "fault is upstream."
    ]
    assert catalogue.load_body("diagnose-input-loss").startswith("1. Call")
    assert "Available skills: diagnose-input-loss" in catalogue.load_body("missing")


def test_catalogue_refuses_two_skills_with_one_name(tmp_path):
    first = write_skill(tmp_path / "a", "diagnose-input-loss", GOOD)
    second = write_skill(tmp_path / "b", "diagnose-input-loss", GOOD)
    with pytest.raises(SkillError, match="defined twice"):
        SkillCatalogue.from_paths([first, second])
