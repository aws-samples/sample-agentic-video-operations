"""RB11: the Hydrolix web app never evaluates model or data output as code."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WEB_SRC = ROOT / "samples/hydrolix/amplify-hydrolix-data-assistant-agentcore-strands/src"
CODE_SINKS = re.compile(
    r"\beval\s*\(|\bnew\s+Function\s*\(|\bFunction\s*\(\s*['\"`]|dangerouslySetInnerHTML"
    r"|\.innerHTML\s*=|\.outerHTML\s*=|insertAdjacentHTML|document\.write"
    r"|set(?:Timeout|Interval)\s*\(\s*['\"`]"
)


def test_the_web_app_has_no_code_or_raw_html_sinks():
    offenders = [
        f"{path.relative_to(ROOT)}:{number}: {line.strip()}"
        for path in sorted(WEB_SRC.rglob("*.js"))
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if CODE_SINKS.search(line)
    ]
    assert not offenders, "\n".join(offenders)


def test_the_guard_catches_the_old_formatter():
    assert CODE_SINKS.search('obj[key] = new Function("return " + obj[key])();')


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_chart_formatters_pass_their_node_tests():
    test_file = Path(__file__).with_name("web") / "hydrolix_chart_formatters.test.mjs"
    result = subprocess.run(
        ["node", "--test", str(test_file)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


APP = WEB_SRC.parent


def test_answers_render_through_the_no_fetch_schema_and_links_open_safely():
    renderer = (WEB_SRC / "components/MarkdownRenderer.js").read_text()
    assert "[rehypeSanitize, MARKDOWN_SCHEMA]" in renderer
    assert 'target="_blank" rel="noopener noreferrer"' in renderer
    assert "<img" not in renderer


@pytest.mark.skipif(
    shutil.which("node") is None or not (APP / "node_modules").is_dir(),
    reason="needs node and the web app's node_modules (the hydrolix-web CI job has both)",
)
def test_the_sanitize_schema_passes_its_node_tests():
    result = subprocess.run(
        ["node", "--test", *map(str, sorted((APP / "test").glob("*.test.mjs")))],
        cwd=APP,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
