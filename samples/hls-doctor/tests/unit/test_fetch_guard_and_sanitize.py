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
    assert clean.body_bytes_b64 is None  # binary bodies never leave the process


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


KEYED_PLAYLIST = (
    "#EXTM3U\n"
    '#EXT-X-KEY:METHOD=AES-128,URI="key?secret=topsecretvalue&hdnts=exp123~hmac456"\n'
    "#EXTINF:6.0,\n"
    "seg1.ts?token=credential-like-value&_HLS_msn=5\n"
)


def test_stored_playlist_bodies_carry_no_query_tokens() -> None:
    exchange = HttpExchange(
        url="https://cdn.example/prog.m3u8",
        requested_url="https://cdn.example/prog.m3u8",
        at_ms=0,
        status=200,
        headers={"content-type": "application/vnd.apple.mpegurl"},
        body_text=KEYED_PLAYLIST,
    )
    stored = EvidenceStore()
    evidence_id = stored.record_exchange(exchange, "media_playlist")
    body = stored.exchanges[evidence_id].body_text or ""
    for secret in ("topsecretvalue", "hmac456", "credential-like-value"):
        assert secret not in body
    assert "secret=REDACTED" in body and "token=REDACTED" in body
    assert "_HLS_msn=5" in body  # structural directives survive
    assert stored.exchanges[evidence_id].body_sha256 is not None


def test_entry_policy_refusal_names_the_policy() -> None:
    from hls_doctor.domain.graph.build_presentation_graph import PresentationGraph
    from hls_doctor.domain.graph.presentation_node import PresentationNode
    from hls_doctor.workflows.inspect_stream import raise_when_entry_transport_failed

    url = "http://127.0.0.1/master.m3u8"
    evidence = EvidenceStore()
    evidence_id = evidence.record_exchange(
        HttpExchange(
            url=url,
            requested_url=url,
            at_ms=0,
            transport_error="RefusedTarget: it resolves to the non-global address 127.0.0.1",
        )  # fmt: skip
    )
    graph = PresentationGraph(entry_url=url)
    graph.nodes[url] = PresentationNode(
        url=url, node_type="media_playlist", evidence_ids=[evidence_id]
    )
    with pytest.raises(ToolFailure) as failure:
        raise_when_entry_transport_failed(url, graph, evidence)
    assert "refused by policy" in failure.value.message
    assert "RefusedTarget" in failure.value.message


def test_ffprobe_local_input_is_an_allowlist(tmp_path) -> None:
    import tempfile

    from hls_doctor.adapters.ffprobe.run_ffprobe import protocol_whitelist

    with tempfile.NamedTemporaryFile(prefix="hls-doctor-media-", suffix=".bin") as own:
        assert protocol_whitelist(own.name) == "file"
    for hostile in (
        "subfile,,start,0,end,100,,:/etc/passwd",
        "concat:/etc/passwd",
        "/etc/passwd",
        str(tmp_path / "other.bin"),
    ):
        with pytest.raises(ToolFailure):
            protocol_whitelist(hostile)


def test_small_binary_bodies_also_never_leave_the_process() -> None:
    key = exchange_with("https://cdn.example/k", {}, bytes(range(16)))
    clean = key.sanitized(1024)
    assert clean.body_bytes_b64 is None
    assert clean.body_sha256 is not None and clean.content_length == 16


def test_playlist_redaction_covers_define_values_and_any_quoted_query() -> None:
    from hls_doctor.adapters.http.redact_url import redact_playlist_body

    body = (
        "#EXTM3U\n"
        '#EXT-X-DEFINE:NAME="token",VALUE="super-secret-token"\n'
        '#EXT-X-DATERANGE:ID="ad",X-ASSET-LIST="https://ads.example/list.json?tok=sneaky"\n'
        "seg1.ts?auth=leakme&_HLS_msn=7\n"
    )
    redacted = redact_playlist_body(body)
    for secret in ("super-secret-token", "sneaky", "leakme"):
        assert secret not in redacted
    assert 'VALUE="REDACTED"' in redacted
    assert "tok=REDACTED" in redacted
    assert "_HLS_msn=7" in redacted


def test_ffprobe_refuses_network_targets_outright() -> None:
    from hls_doctor.adapters.ffprobe.run_ffprobe import protocol_whitelist

    for target in ("http://cdn.example/seg.m4s", "https://cdn.example/seg.m4s"):
        with pytest.raises(ToolFailure) as failure:
            protocol_whitelist(target)
        assert "local" in failure.value.message.lower()
