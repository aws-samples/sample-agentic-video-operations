"""Run a model-written processing script over tool data (code_mode, opt-in only).

Only reachable when ENABLE_CODE_MODE=true. Responses under the threshold run in this
process with `exec`, which executes model-written Python: enable it only in a sandboxed
runtime you trust. Larger responses go to the AgentCore Code Interpreter sandbox.
"""

import contextlib
import io
import json

LOCAL_THRESHOLD_BYTES = 524_288


def run_processing_script(data_json: str, script: str, code_interpreter) -> tuple[bool, str, str]:
    """Return (succeeded, stdout, error)."""
    if len(data_json.encode()) >= LOCAL_THRESHOLD_BYTES:
        result = code_interpreter.execute(data_json, script)
        error = "" if result.success else f"{result.error_type}: {result.error_message}"
        return result.success, result.stdout or "", error
    namespace = {"DATA": data_json, "json": json}
    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output):
            exec(script, namespace)  # noqa: S102 - opt-in, see module docstring
    except Exception as error:  # boundary: the script is arbitrary model output
        return False, output.getvalue(), f"{type(error).__name__}: {error}"
    return True, output.getvalue(), ""
