"""Create one bucket-scoped InfluxDB read token through a local SSM tunnel."""

import base64
import json
import ssl
from dataclasses import dataclass
from http.cookiejar import CookieJar
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import (
    HTTPCookieProcessor,
    HTTPSHandler,
    OpenerDirector,
    Request,
    build_opener,
)


class InfluxApiError(RuntimeError):
    """A safe-to-print failure from the InfluxDB API."""


@dataclass(frozen=True)
class InfluxAdminCredentials:
    username: str
    password: str
    organization: str
    bucket: str
    read_token: str | None = None


READ_TOKEN_DESCRIPTION = "cmcd-mcp-server read-only"


def _build_tunnel_opener() -> OpenerDirector:
    """Build an opener for localhost, where the remote certificate name cannot match."""
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return build_opener(HTTPSHandler(context=context), HTTPCookieProcessor(CookieJar()))


def _request_json(
    opener: OpenerDirector,
    request: Request,
) -> dict[str, Any]:
    body = _request_bytes(opener, request)
    if not body:
        return {}
    try:
        decoded = json.loads(body)
    except json.JSONDecodeError as error:
        raise InfluxApiError("InfluxDB returned an invalid JSON response.") from error
    if not isinstance(decoded, dict):
        raise InfluxApiError("InfluxDB returned an unexpected response.")
    return decoded


def _request_bytes(
    opener: OpenerDirector,
    request: Request,
    *,
    expected_status: int | None = None,
) -> bytes:
    try:
        with opener.open(request, timeout=30) as response:
            status = getattr(response, "status", response.getcode())
            body = response.read()
    except HTTPError as error:
        if error.code == expected_status:
            return error.read()
        raise InfluxApiError(f"InfluxDB rejected the request (HTTP {error.code}).") from error
    except (URLError, TimeoutError) as error:
        raise InfluxApiError(
            "Could not reach InfluxDB. Keep the Systems Manager tunnel running."
        ) from error
    if expected_status is not None and status != expected_status:
        raise InfluxApiError(f"InfluxDB returned HTTP {status}; expected HTTP {expected_status}.")
    return body


def _find_resource_id(response: dict[str, Any], collection: str, resource_name: str) -> str:
    resources = response.get(collection)
    if not isinstance(resources, list):
        raise InfluxApiError(f"InfluxDB did not return the {collection} collection.")
    match = next(
        (
            item
            for item in resources
            if isinstance(item, dict)
            and item.get("name") == resource_name
            and isinstance(item.get("id"), str)
        ),
        None,
    )
    if match is None:
        raise InfluxApiError(f"InfluxDB {collection[:-1]} {resource_name!r} was not found.")
    return match["id"]


def create_influxdb_read_token(
    base_url: str,
    credentials: InfluxAdminCredentials,
    *,
    opener: OpenerDirector | None = None,
) -> str:
    """Sign in and create a token that can only read the configured bucket."""
    client = opener or _build_tunnel_opener()
    basic = base64.b64encode(f"{credentials.username}:{credentials.password}".encode()).decode()
    _request_json(
        client,
        Request(
            f"{base_url}/api/v2/signin",
            method="POST",
            headers={"Authorization": f"Basic {basic}"},
        ),
    )

    org_response = _request_json(
        client,
        Request(f"{base_url}/api/v2/orgs?{urlencode({'org': credentials.organization})}"),
    )
    org_id = _find_resource_id(org_response, "orgs", credentials.organization)
    bucket_response = _request_json(
        client,
        Request(
            f"{base_url}/api/v2/buckets?{urlencode({'name': credentials.bucket, 'orgID': org_id})}"
        ),
    )
    bucket_id = _find_resource_id(bucket_response, "buckets", credentials.bucket)
    if credentials.read_token:
        verify_influxdb_read_token(
            base_url,
            credentials.organization,
            credentials.bucket,
            credentials.read_token,
            opener=client,
        )
        return credentials.read_token

    authorizations = _request_json(
        client,
        Request(
            f"{base_url}/api/v2/authorizations?{urlencode({'orgID': org_id})}",
        ),
    ).get("authorizations")
    if isinstance(authorizations, list):
        for authorization in authorizations:
            if (
                isinstance(authorization, dict)
                and authorization.get("description") == READ_TOKEN_DESCRIPTION
                and _has_bucket_permission(authorization, "read", org_id, bucket_id)
                and isinstance(authorization.get("token"), str)
                and authorization["token"]
            ):
                token = authorization["token"]
                verify_influxdb_read_token(
                    base_url,
                    credentials.organization,
                    credentials.bucket,
                    token,
                    opener=client,
                )
                return token

    payload = {
        "orgID": org_id,
        "description": READ_TOKEN_DESCRIPTION,
        "permissions": [_bucket_permission("read", org_id, bucket_id)],
    }
    token_response = _request_json(
        client,
        Request(
            f"{base_url}/api/v2/authorizations",
            data=json.dumps(payload).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        ),
    )
    token = token_response.get("token")
    if not isinstance(token, str) or not token:
        raise InfluxApiError("InfluxDB created an authorization without returning its token.")
    verify_influxdb_read_token(
        base_url,
        credentials.organization,
        credentials.bucket,
        token,
        opener=client,
    )
    return token


def _bucket_permission(action: str, org_id: str, bucket_id: str) -> dict[str, Any]:
    return {
        "action": action,
        "resource": {"type": "buckets", "id": bucket_id, "orgID": org_id},
    }


def _has_bucket_permission(
    authorization: dict[str, Any],
    action: str,
    org_id: str,
    bucket_id: str,
) -> bool:
    permissions = authorization.get("permissions")
    if not isinstance(permissions, list) or len(permissions) != 1:
        return False
    permission = permissions[0]
    if not isinstance(permission, dict) or permission.get("action") != action:
        return False
    resource = permission.get("resource")
    return (
        isinstance(resource, dict)
        and resource.get("type") == "buckets"
        and resource.get("id") == bucket_id
        and resource.get("orgID") == org_id
    )


def verify_influxdb_read_token(
    base_url: str,
    organization: str,
    bucket: str,
    token: str,
    *,
    opener: OpenerDirector | None = None,
) -> None:
    """Require a successful bucket read and a forbidden bucket write."""
    client = opener or _build_tunnel_opener()
    headers = {
        "Authorization": f"Token {token}",
        "Content-Type": "application/vnd.flux",
    }
    query = f'from(bucket: "{bucket}") |> range(start: -1h) |> limit(n: 1)'.encode()
    _request_bytes(
        client,
        Request(
            f"{base_url}/api/v2/query?{urlencode({'org': organization})}",
            data=query,
            method="POST",
            headers=headers,
        ),
        expected_status=200,
    )
    write_url = f"{base_url}/api/v2/write?{
        urlencode(
            {
                'org': organization,
                'bucket': bucket,
                'precision': 'ns',
            }
        )
    }"
    _request_bytes(
        client,
        Request(
            write_url,
            data=b"cmcd_token_permission_check value=1i",
            method="POST",
            headers={"Authorization": f"Token {token}", "Content-Type": "text/plain"},
        ),
        expected_status=403,
    )
