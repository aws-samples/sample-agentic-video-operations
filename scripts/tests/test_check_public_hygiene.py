from pathlib import Path

import pytest
from check_public_hygiene import find_internal_labels, list_public_paths


@pytest.mark.parametrize(
    "parts",
    [
        ("C", "3.2"),
        ("G", "4.2"),
        ("R", "1"),
        ("T", "41"),
        ("T", "79", "b"),
        ("RB", "9"),
        ("REN", "1"),
        ("F", "3"),
        ("F", "3-B", "1"),
        ("PR", "30-", "7"),
    ],
)
def test_internal_plan_labels_are_reported(parts):
    label = "".join(parts)
    assert find_internal_labels(Path("sample.py"), f"public text {label}")


def test_lockfile_integrity_is_not_mistaken_for_a_plan_label():
    integrity = '"integrity": "sha512-exampleF7/exampleRB9+value=="'
    assert find_internal_labels(Path("package-lock.json"), integrity) == []


def test_python_lint_codes_are_not_mistaken_for_feature_labels():
    lint_directive = "from fixtures import data  # noqa: " + "F" + "401"
    assert find_internal_labels(Path("test_sample.py"), lint_directive) == []


def test_long_base64_runs_are_not_mistaken_for_plan_labels():
    encoded = "aGVsbG8vV" + "T" + "87c29tZS9sb25nL2Jhc2U2NC9wYXlsb2FkPT0="
    assert len(encoded) >= 32
    assert find_internal_labels(Path("fixture.json"), encoded) == []


@pytest.mark.parametrize("text", ["Cloudflare R2", "T3 instance", "F1 score"])
def test_ordinary_numbered_terms_are_not_mistaken_for_plan_labels(text):
    assert find_internal_labels(Path("README.md"), text) == []


def test_published_builder_instructions_are_scanned():
    assert Path(".claude/CLAUDE.md") in list_public_paths()
    label = "T" + "83"
    assert find_internal_labels(Path(".claude/CLAUDE.md"), label)
