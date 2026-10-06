"""Classify an AWS CLI failure by its error code only, never by words in the message.

Error text carries the caller ARN and account id, so a bare "404" or "NotFound" can appear
in an AccessDenied message. Only the `An error occurred (<code>)` slot is trusted.
"""

import re
import subprocess

MISSING_ERROR_CODE = re.compile(
    r"An error occurred \((ResourceNotFoundException|ParameterNotFound|NoSuchBucket|NotFound|404)\)"
)
MISSING_STACK = re.compile(r"Stack with id \S+ does not exist")


def is_missing_resource(result: subprocess.CompletedProcess[str]) -> bool:
    message = f"{result.stdout}\n{result.stderr}"
    return bool(MISSING_ERROR_CODE.search(message) or MISSING_STACK.search(message))


def describe_failure(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout).strip() or f"AWS CLI exited {result.returncode}"
