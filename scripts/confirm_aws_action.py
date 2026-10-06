"""Ask before a billable or destructive AWS action (`just deploy` / `just destroy`).

Prints the action, target, account, region and any details, then asks [y/N] unless --yes
is given. Exit code 0 means go ahead; 1 means cancelled or the account could not be read.
Sample scripts such as manage_cmcd_stack.py reuse `ask_to_continue`.
"""

import argparse
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field

NO_CREDENTIALS_FIX = "No valid AWS credentials. Fix: aws configure sso  # or export AWS_PROFILE"


@dataclass(frozen=True)
class ConfirmationPrompt:
    action: str
    target: str
    region: str
    account: str
    details: dict[str, str] = field(default_factory=dict)


def read_account_id() -> str | None:
    command = ("aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text")
    result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def ask_to_continue(
    prompt: ConfirmationPrompt, *, assume_yes: bool, ask: Callable[[str], str] = input
) -> bool:
    """Print what is about to happen; return True only on --yes or an explicit "y"."""
    print(f"{prompt.action} {prompt.target}")
    print(f"  account: {prompt.account}")
    print(f"  region:  {prompt.region}")
    for name, value in prompt.details.items():
        print(f"  {name}: {value}")
    if assume_yes:
        return True
    if ask("Continue? [y/N] ").strip().lower() == "y":
        return True
    print("Cancelled.")
    return False


def parse_arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", required=True, help="e.g. 'deploy (billable: ...)'")
    parser.add_argument("--target", required=True, help="stack or sample name")
    parser.add_argument("--region", required=True)
    parser.add_argument("--yes", action="store_true", help="skip the prompt")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    arguments = parse_arguments(argv)
    account = read_account_id()
    if account is None:
        print(NO_CREDENTIALS_FIX)
        return 1
    prompt = ConfirmationPrompt(arguments.action, arguments.target, arguments.region, account)
    return 0 if ask_to_continue(prompt, assume_yes=arguments.yes) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
