"""The Hydrolix web app: its stream parser and logger tests run, and nothing else logs.

The browser console is a log sink too, so the app logs through utils/logMetadata.js
only (event names, counts and lengths). Any other console call in src/ fails here.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WEB_SRC = ROOT / "samples/hydrolix/amplify-hydrolix-data-assistant-agentcore-strands/src"
LOGGER = WEB_SRC / "utils/logMetadata.js"
CONSOLE_CALL = re.compile(r"\bconsole\s*\.\s*[a-zA-Z]+\s*\(|\(\s*console\s*\.\s*[a-zA-Z]+\s*\)")


def test_only_the_metadata_logger_touches_the_console():
    offenders = []
    for path in sorted(WEB_SRC.rglob("*.js")):
        if path == LOGGER:
            continue
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if line.lstrip().startswith("//"):
                continue
            if CONSOLE_CALL.search(line) or ".catch(console." in line:
                offenders.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
    assert not offenders, "log through utils/logMetadata.js instead:\n" + "\n".join(offenders)


def test_the_guard_catches_the_forms_it_must():
    for line in ('console.log("x", answer)', "console.error(error)", ".catch(console.error)"):
        assert CONSOLE_CALL.search(line) or ".catch(console." in line, line


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_web_app_stream_parser_and_logger_pass_their_node_tests():
    result = subprocess.run(
        ["node", "--test", str(Path(__file__).with_name("web") / "hydrolix_web_app.test.mjs")],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
