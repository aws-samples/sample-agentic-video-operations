"""Ask before a billable or destructive AWS action (`just deploy` / `just destroy`).

Prints the action, target, account and region, then asks [y/N] unless --yes is given.
Exit code 0 means go ahead; 1 means cancelled or the account could not be read.
"""

import argparse
import subprocess
import sys


def read_account_id() -> str | None:
    command = ("aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text")
    result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


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
        print("No valid AWS credentials. Fix: aws configure sso  # or export AWS_PROFILE")
        return 1
    print(f"{arguments.action} {arguments.target}")
    print(f"  account: {account}")
    print(f"  region:  {arguments.region}")
    if arguments.yes:
        return 0
    answer = input("Continue? [y/N] ").strip().lower()
    if answer != "y":
        print("Cancelled.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
