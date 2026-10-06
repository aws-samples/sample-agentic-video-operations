import base64
import json

from create_influxdb_read_token import (
    InfluxAdminCredentials,
    create_influxdb_read_token,
)


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        if self.payload is None:
            return b""
        if isinstance(self.payload, bytes):
            return self.payload
        return json.dumps(self.payload).encode()

    def getcode(self):
        return self.status


class FakeOpener:
    def __init__(self):
        self.requests = []
        self.responses = [
            FakeResponse(None, 204),
            FakeResponse({"orgs": [{"id": "org-1", "name": "cmcd-org"}]}),
            FakeResponse({"buckets": [{"id": "bucket-1", "name": "cmcd-metrics"}]}),
            FakeResponse({"authorizations": []}),
            FakeResponse({"token": "read-token-secret"}, 201),
            FakeResponse(b"result,table"),
            FakeResponse(None, 403),
        ]

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        return self.responses.pop(0)


def test_create_token_signs_in_and_requests_only_bucket_read_permission():
    opener = FakeOpener()
    credentials = InfluxAdminCredentials(
        username="admin",
        password="password-secret",
        organization="cmcd-org",
        bucket="cmcd-metrics",
    )

    token = create_influxdb_read_token(
        "https://localhost:8086",
        credentials,
        opener=opener,
    )

    assert token == "read-token-secret"
    signin = opener.requests[0][0]
    expected_basic = base64.b64encode(b"admin:password-secret").decode()
    assert signin.full_url.endswith("/api/v2/signin")
    assert signin.headers["Authorization"] == f"Basic {expected_basic}"
    authorization = opener.requests[4][0]
    payload = json.loads(authorization.data)
    assert payload["description"] == "cmcd-mcp-server read-only"
    assert payload["permissions"] == [
        {
            "action": "read",
            "resource": {"type": "buckets", "id": "bucket-1", "orgID": "org-1"},
        }
    ]
    read_check = opener.requests[5][0]
    write_check = opener.requests[6][0]
    assert "/api/v2/query?" in read_check.full_url
    assert read_check.headers["Authorization"] == "Token read-token-secret"
    assert "/api/v2/write?" in write_check.full_url


def test_create_token_reuses_matching_authorization_and_verifies_permissions():
    opener = FakeOpener()
    opener.responses = [
        FakeResponse(None, 204),
        FakeResponse({"orgs": [{"id": "org-1", "name": "cmcd-org"}]}),
        FakeResponse({"buckets": [{"id": "bucket-1", "name": "cmcd-metrics"}]}),
        FakeResponse(
            {
                "authorizations": [
                    {
                        "description": "cmcd-mcp-server read-only",
                        "token": "existing-read-token",
                        "permissions": [
                            {
                                "action": "read",
                                "resource": {
                                    "type": "buckets",
                                    "id": "bucket-1",
                                    "orgID": "org-1",
                                    "name": "cmcd-metrics",
                                },
                            }
                        ],
                    }
                ]
            }
        ),
        FakeResponse(b"result,table"),
        FakeResponse(None, 403),
    ]

    token = create_influxdb_read_token(
        "https://localhost:8086",
        InfluxAdminCredentials("admin", "password", "cmcd-org", "cmcd-metrics"),
        opener=opener,
    )

    assert token == "existing-read-token"
    assert sum(request.get_method() == "POST" for request, _ in opener.requests) == 3
