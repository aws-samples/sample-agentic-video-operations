from check_model_ids import MODEL_ID_PATTERN, find_unknown_model_ids
from model_ids import ALLOWED_MODEL_IDS


def test_pattern_matches_the_id_shapes_in_use() -> None:
    line = (
        "us.anthropic.claude-sonnet-4-6 global.anthropic.claude-haiku-4-5-20251001-v1:0 "
        "anthropic.claude-sonnet-4-6 us.amazon.nova-pro-v1:0"
    )
    assert MODEL_ID_PATTERN.findall(line) == [
        "us.anthropic.claude-sonnet-4-6",
        "global.anthropic.claude-haiku-4-5-20251001-v1:0",
        "anthropic.claude-sonnet-4-6",
        "us.amazon.nova-pro-v1:0",
    ]


def test_pattern_does_not_match_prose() -> None:
    assert MODEL_ID_PATTERN.findall("Claude Sonnet reads anthropic documentation") == []


def test_allowlist_ids_match_their_own_pattern() -> None:
    for model_id in ALLOWED_MODEL_IDS:
        assert MODEL_ID_PATTERN.fullmatch(model_id), model_id


def test_repository_has_no_unknown_model_ids() -> None:
    assert find_unknown_model_ids() == []
