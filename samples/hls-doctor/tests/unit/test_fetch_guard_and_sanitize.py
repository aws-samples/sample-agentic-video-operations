import base64
import json

import httpx
import pytest

from hls_doctor.adapters.http.fetch_url import create_live_fetch
from hls_doctor.adapters.http.guard_fetch_target import guard_fetch_target
from hls_doctor.adapters.http.http_exchange import HttpExchange
from hls_doctor.domain.evidence.evidence_store import EvidenceStore
from media_ops_contracts.tool_failure import ToolFailure

PUBLIC = ["93.184.216.34"]


def resolver(table):
    def resolve(host):
        return table[host]

    return resolve


@pytest.mark.parametrize(
    "target",
    [
        "http://127.0.0.1/master.m3u8",
        "http://10.0.0.5/master.m3u8",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/master.m3u8",
        "http://[fe80::1]/master.m3u8",
    ],
)
def test_guard_refuses_non_global_address_literals(target) -> None:
    with pytest.raises(ToolFailure) as failure:
        guard_fetch_target(target)
    assert "non-global address" in failure.value.message


def test_guard_refuses_hostnames_resolving_to_loopback() -> None:
    with pytest.raises(ToolFailure):
        guard_fetch_target(
            "http://cdn.example/x.m3u8", resolve=resolver({"cdn.example": ["127.0.0.1"]})
        )


def test_guard_accepts_global_hosts_and_private_optin_locally(monkeypatch) -> None:
    monkeypatch.delenv("DOCKER_CONTAINER", raising=False)
    guard_fetch_target("https://cdn.example/x.m3u8", resolve=resolver({"cdn.example": PUBLIC}))
    guard_fetch_target("http://127.0.0.1/x.m3u8", allow_private=True)


def test_private_optin_is_refused_inside_the_container(monkeypatch) -> None:
    monkeypatch.setenv("DOCKER_CONTAINER", "1")
    with pytest.raises(ToolFailure) as failure:
        guard_fetch_target("http://127.0.0.1/x.m3u8", allow_private=True)
    assert "container" in failure.value.message


def test_guard_refuses_non_http_schemes() -> None:
    with pytest.raises(ToolFailure):
        guard_fetch_target("file:///etc/hosts")


def fetch_with(transport, table):
    return create_live_fetch(
        timeout_seconds=5,
        user_agent="test",
        resolve=resolver(table),
        transport=transport,
    )


def test_redirect_to_loopback_is_refused_and_becomes_evidence() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})

    fetch = fetch_with(httpx.MockTransport(handler), {"cdn.example": PUBLIC})
    exchange = fetch("http://cdn.example/master.m3u8")
    assert exchange.transport_error is not None
    assert "RefusedTarget" in exchange.transport_error
    assert exchange.redirects == ["http://cdn.example/master.m3u8"]


def test_declared_oversize_body_is_not_read() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-length": str(50_000_000), "content-type": "video/mp4"}
        )

    fetch = fetch_with(httpx.MockTransport(handler), {"cdn.example": PUBLIC})
    exchange = fetch("http://cdn.example/big.mp4")
    assert exchange.body_truncated and exchange.content_length == 0


def test_streamed_body_stops_at_the_decoded_cap() -> None:
    def chunks():  # chunked transfer: no content-length header to pre-check
        for _ in range(80):
            yield b"x" * 65_536

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=chunks(), headers={"content-type": "video/mp4"})

    fetch = fetch_with(httpx.MockTransport(handler), {"cdn.example": PUBLIC})
    exchange = fetch("http://cdn.example/big.mp4")
    assert exchange.body_truncated
    assert exchange.content_length == 4_000_000


def exchange_with(url: str, headers: dict, body: bytes) -> HttpExchange:
    return HttpExchange(
        url=url, requested_url=url, at_ms=0, status=200, headers=headers,
        body_bytes_b64=base64.b64encode(body).decode(), content_length=len(body),
    )  # fmt: skip


def test_sanitized_exchange_drops_cookies_and_redacts_queries() -> None:
    exchange = exchange_with(
        "https://cdn.example/key?hdnts=exp1~hmac2",
        {"set-cookie": "cdn=secret", "x-amz-cf-id": "abc", "content-type": "text/plain"},
        b"0123456789" * 200,
    )
    clean = exchange.sanitized(16)
    assert "hdnts=REDACTED" in clean.url
    assert "set-cookie" not in clean.headers and "x-amz-cf-id" not in clean.headers
    assert clean.headers["content-type"] == "text/plain"
    assert clean.body_truncated and clean.body_sha256 is not None
    assert len(base64.b64decode(clean.body_bytes_b64 or "")) == 16


def test_key_exchanges_keep_no_body_at_all() -> None:
    store = EvidenceStore()
    evidence_id = store.record_exchange(
        exchange_with("https://cdn.example/content.key", {}, bytes(range(16))),
        resource_type="key",
    )
    stored = store.exchanges[evidence_id]
    assert stored.body_bytes_b64 is None and stored.body_text is None
    assert stored.body_sha256 is not None and stored.content_length == 16


def test_report_json_never_contains_the_key_bytes() -> None:
    key_bytes = bytes(range(16))
    store = EvidenceStore()
    store.record_exchange(
        exchange_with("https://cdn.example/content.key", {}, key_bytes),
        resource_type="key",
    )
    dumped = json.dumps(store.model_dump(mode="json"))
    assert base64.b64encode(key_bytes).decode() not in dumped
