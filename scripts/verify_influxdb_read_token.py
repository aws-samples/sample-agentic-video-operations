"""Verify that the root .env InfluxDB token can read but cannot write."""

import os
import sys

from create_influxdb_read_token import InfluxApiError, verify_influxdb_read_token
from read_root_env import describe_root_env, load_root_env

from cmcd_mcp.settings.runtime_settings import DEFAULT_INFLUXDB_BUCKET


def main() -> int:
    required = ("INFLUXDB_URL", "INFLUXDB_ORG", "INFLUXDB_TOKEN")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        names = ", ".join(missing)
        print(f"Missing {names}: not set in the environment or in {describe_root_env()}.")
        return 1
    try:
        verify_influxdb_read_token(
            os.environ["INFLUXDB_URL"],
            os.environ["INFLUXDB_ORG"],
            os.environ.get("INFLUXDB_BUCKET") or DEFAULT_INFLUXDB_BUCKET,
            os.environ["INFLUXDB_TOKEN"],
        )
    except InfluxApiError as error:
        print(error)
        return 1
    print("read 200; write 403")
    return 0


if __name__ == "__main__":
    load_root_env(os.environ)
    sys.exit(main())
