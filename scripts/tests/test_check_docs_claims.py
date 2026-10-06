"""Docs may only name recipes, sample commands and paths that exist."""

from pathlib import Path

import check_docs_claims as claims

JUSTFILE = """
demo:
    uv run demo-hub

eval:
    @just _pending_eval

deploy sample *flags:
    #!/usr/bin/env bash
    case "{{ sample }}" in
      hub)      uv run python scripts/manage_hub_stack.py deploy ;;
      medialive|mediaconnect) echo "deploys through the hub" >&2; exit 1 ;;
      langchain) just _pending "{{ sample }}" ;;
      *) just _unknown "{{ sample }}" ;;
    esac
"""
RECIPES = claims.read_recipes(JUSTFILE)


def problems(text):
    return claims.find_problems(Path("README.md"), text, RECIPES)


def test_existing_recipes_and_handled_samples_pass():
    assert problems("Run `just demo`, then `just deploy hub`.") == []


def test_a_missing_recipe_fails():
    assert problems("`just demo-channel delete`") == [
        "README.md: `just demo-channel` is not a recipe"
    ]


def test_a_placeholder_recipe_fails():
    assert problems("```bash\njust eval\n```") == ["README.md: `just eval` is only a placeholder"]


def test_an_unimplemented_or_redirected_sample_fails():
    assert problems("`just deploy langchain`") == [
        "README.md: `just deploy langchain` is not implemented"
    ]  # noqa: E501
    assert problems("`just deploy medialive`") == [
        "README.md: `just deploy medialive` is not implemented"
    ]  # noqa: E501


def test_a_missing_repository_path_fails_and_templates_are_skipped():
    assert problems("see `samples/nowhere/cdk`") == [
        "README.md: samples/nowhere/cdk does not exist"
    ]
    assert problems("see `samples/<key>/README.md`") == []


def test_the_real_justfile_parses():
    recipes = claims.read_recipes((claims.ROOT / "justfile").read_text())
    assert {"demo", "deploy", "destroy", "docs-check"} <= set(recipes)
    assert "hub" in claims.handled_samples(recipes["deploy"])


def test_an_untracked_local_file_does_not_satisfy_a_path_claim():
    tracked = frozenset({"samples", "samples/hub", "samples/hub/README.md"})
    text = "see `samples/hub/README.md` and `samples/hub/cdk/node_modules/.bin/cdk`"
    assert claims.find_problems(Path("README.md"), text, RECIPES, tracked) == [
        "README.md: samples/hub/cdk/node_modules/.bin/cdk does not exist"
    ]


def test_plan_language_presented_as_product_state_fails():
    text = "The runtime has not landed.\nNo own deploy after step 4.\nFollow step 5 of Run Locally."
    found = problems(text)
    assert "README.md:1: plan language as product state: 'has not landed'" in found
    assert "README.md:2: plan language as product state: 'after step 4'" in found
    assert len(found) == 2  # a numbered instruction step is not plan language
