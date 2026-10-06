"""Execute one Flux query against InfluxDB."""

from typing import Any
from urllib.parse import urlparse

from influxdb_client import InfluxDBClient
from influxdb_client.client.exceptions import InfluxDBError
from urllib3.exceptions import HTTPError

from media_ops_contracts.tool_failure import FailureKind, ToolFailure


def query_influxdb(
    flux: str,
    *,
    url: str,
    token: str,
    org: str,
    verify_ssl: bool,
) -> list[dict[str, Any]]:
    """Return normalized records for one Flux query."""
    if urlparse(url).scheme not in {"http", "https"}:
        raise ToolFailure(
            FailureKind.INVALID_REQUEST,
            "INFLUXDB_URL must use http or https.",
            "Set a valid INFLUXDB_URL in the root .env.",
        )
    if not token:
        raise ToolFailure(
            FailureKind.INVALID_REQUEST,
            "INFLUXDB_TOKEN is empty.",
            "Set INFLUXDB_TOKEN in the root .env.",
        )

    client = InfluxDBClient(
        url=url,
        token=token,
        org=org,
        timeout=10_000,
        verify_ssl=verify_ssl,
    )
    try:
        tables = client.query_api().query(org=org, query=flux)
        return [_normalize_record(record) for table in tables for record in table.records]
    except (InfluxDBError, HTTPError) as error:
        raise ToolFailure(
            FailureKind.EXTERNAL_SERVICE_UNAVAILABLE,
            "The InfluxDB query failed.",
            "Check the InfluxDB URL, token, organization, and network path.",
        ) from error
    finally:
        client.close()


def _normalize_record(record: Any) -> dict[str, Any]:
    values = dict(record.values)
    timestamp = values.get("_time")
    if hasattr(timestamp, "isoformat"):
        values["_time"] = timestamp.isoformat()
    return values
