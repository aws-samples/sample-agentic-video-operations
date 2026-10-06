"""Verify that the root .env InfluxDB token can read but cannot write."""

import os
import sys

from create_influxdb_read_token import InfluxApiError, verify_influxdb_read_token


def main() -> int:
    required = ("INFLUXDB_URL", "INFLUXDB_ORG", "INFLUXDB_TOKEN")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        print(f"Missing root .env values: {', '.join(missing)}")
        return 1
    try:
        verify_influxdb_read_token(
            os.environ["INFLUXDB_URL"],
            os.environ["INFLUXDB_ORG"],
            "cmcd-metrics",
            os.environ["INFLUXDB_TOKEN"],
        )
    except InfluxApiError as error:
        print(error)
        return 1
    print("read 200; write 403")
    return 0


if __name__ == "__main__":
    sys.exit(main())
