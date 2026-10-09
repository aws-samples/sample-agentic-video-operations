"""Live HTTP fetch: guarded, streamed, bounded; errors become evidence.

Every request - including every redirect hop, which is followed manually -
passes the SSRF guard immediately before connecting. Bodies are read as a
stream and stop at the decoded-byte cap, so neither a large object nor a
compression bomb is materialised; a Content-Length above the cap is not
read at all. What was read is truncated evidence, never a failure.
"""

import base64
import time
import zlib
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from hls_doctor.adapters.http.guard_fetch_target import ResolveHost, guard_fetch_target
from hls_doctor.adapters.http.guard_fetch_target import (
    resolve_with_system_dns as system_dns,
)
from hls_doctor.adapters.http.http_exchange import FetchUrl, HttpExchange
from media_ops_contracts.tool_failure import ToolFailure

TEXT_CONTENT_MARKERS = ("mpegurl", "text", "json", "xml")
MAX_BODY_BYTES = 4_000_000
MAX_REDIRECT_HOPS = 5
# One deadline covers a whole fetch call - every redirect hop and every chunk -
# on top of httpx's per-operation timeout, so a server dripping bytes just
# under the read timeout is still cut off.
TOTAL_DEADLINE_FACTOR = 4


def create_live_fetch(
    *,
    timeout_seconds: float,
    user_agent: str,
    extra_headers: dict[str, str] | None = None,
    clock: Callable[[], datetime] | None = None,
    allow_private_targets: bool = False,
    resolve: ResolveHost = system_dns,
    transport: httpx.BaseTransport | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> FetchUrl:
    """A FetchUrl backed by httpx; transport errors are recorded, not raised."""
    client = httpx.Client(
        timeout=timeout_seconds,
        headers={"User-Agent": user_agent, **(extra_headers or {})},
        follow_redirects=False,
        transport=transport,
    )
    read_now = clock or (lambda: datetime.now(UTC))
    epoch = read_now()
    deadline_seconds = timeout_seconds * TOTAL_DEADLINE_FACTOR

    def fetch(url: str, *, range_header: str | None = None) -> HttpExchange:
        at_ms = int((read_now() - epoch).total_seconds() * 1000)
        headers = {"Range": range_header} if range_header else {}
        started = time.monotonic()
        deadline_at = monotonic() + deadline_seconds
        hops: list[str] = []
        target = url
        try:
            for _ in range(MAX_REDIRECT_HOPS + 1):
                if monotonic() >= deadline_at:
                    break
                guard_fetch_target(target, allow_private=allow_private_targets, resolve=resolve)
                with client.stream("GET", target, headers=headers) as response:
                    ttfb_ms = (time.monotonic() - started) * 1000
                    if response.is_redirect and response.headers.get("location"):
                        hops.append(target)
                        target = str(response.next_request.url) if response.next_request else ""
                        continue
                    exchange = read_exchange(
                        url, target, response, at_ms, started, ttfb_ms, hops,
                        deadline_at=deadline_at, monotonic=monotonic,
                    )  # fmt: skip
                    return exchange
            if monotonic() >= deadline_at:
                return HttpExchange(
                    url=target, requested_url=url, at_ms=at_ms,
                    transport_error="DeadlineExceeded", body_truncated=True,
                    total_ms=(time.monotonic() - started) * 1000, redirects=hops,
                )  # fmt: skip
            return HttpExchange(
                url=target, requested_url=url, at_ms=at_ms,
                transport_error="TooManyRedirects",
                total_ms=(time.monotonic() - started) * 1000, redirects=hops,
            )  # fmt: skip
        except ToolFailure as refusal:
            # A refused hop is delivery evidence: the crawl survives, the
            # exchange names the refusal, and no request was sent.
            return HttpExchange(
                url=target, requested_url=url, at_ms=at_ms,
                transport_error=f"RefusedTarget: {refusal.message}",
                total_ms=(time.monotonic() - started) * 1000, redirects=hops,
            )  # fmt: skip
        except httpx.HTTPError as error:
            return HttpExchange(
                url=target, requested_url=url, at_ms=at_ms,
                transport_error=type(error).__name__,
                total_ms=(time.monotonic() - started) * 1000, redirects=hops,
            )  # fmt: skip

    return fetch


def read_exchange(
    requested_url: str,
    final_url: str,
    response: httpx.Response,
    at_ms: int,
    started: float,
    ttfb_ms: float,
    hops: list[str],
    *,
    deadline_at: float = float("inf"),
    monotonic: Callable[[], float] = time.monotonic,
) -> HttpExchange:
    body, truncated, deadline_hit = read_bounded_body(
        response, deadline_at=deadline_at, monotonic=monotonic
    )
    total_ms = (time.monotonic() - started) * 1000
    content_type = response.headers.get("content-type", "").lower()
    is_text = any(marker in content_type for marker in TEXT_CONTENT_MARKERS)
    return HttpExchange(
        url=final_url,
        requested_url=requested_url,
        at_ms=at_ms,
        status=response.status_code,
        transport_error="DeadlineExceeded" if deadline_hit else None,
        headers=dict(response.headers),
        body_text=body.decode("utf-8", errors="replace") if is_text else None,
        body_bytes_b64=None if is_text else base64.b64encode(body).decode(),
        body_truncated=truncated,
        content_length=len(body),
        ttfb_ms=ttfb_ms,
        redirects=hops,
        total_ms=total_ms,
    )


def read_bounded_body(
    response: httpx.Response,
    *,
    deadline_at: float = float("inf"),
    monotonic: Callable[[], float] = time.monotonic,
) -> tuple[bytes, bool, bool]:
    """(body, truncated, deadline hit): bounded in bytes and in time.

    The raw wire bytes are decompressed here with a per-call output bound
    (`decompressobj(...).decompress(data, max_length=remaining)`), so a
    compression bomb never expands past the cap even within one chunk, and
    the fetch-wide deadline is checked between chunks, so a dripping body
    cannot outlive it.
    """
    declared = response.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        return b"", True, False
    if response.is_stream_consumed:
        # A preloaded body (already decoded in memory): cap-slice it directly.
        content = response.content
        return content[:MAX_BODY_BYTES], len(content) > MAX_BODY_BYTES, False
    decoder = BoundedDecoder(response.headers.get("content-encoding", "identity"))
    collected = bytearray()
    for chunk in response.iter_raw(chunk_size=65536):
        if monotonic() >= deadline_at:
            return bytes(collected), True, True
        remaining = MAX_BODY_BYTES - len(collected)
        if remaining <= 0:
            return bytes(collected), True, False
        piece, overflowed = decoder.decode(chunk, remaining)
        collected.extend(piece)
        if overflowed:
            return bytes(collected), True, False
    return bytes(collected), False, False


class BoundedDecoder:
    """gzip/deflate/identity decoding with a hard output bound per call."""

    def __init__(self, content_encoding: str) -> None:
        encoding = content_encoding.strip().lower()
        # zlib does not export its decompressor type publicly.
        self.decompressor: Any = None
        if encoding in ("gzip", "x-gzip"):
            self.decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
        elif encoding == "deflate":
            # zlib-wrapped per the RFC; +32 auto-detects a raw-gzip mislabel.
            self.decompressor = zlib.decompressobj(32 + zlib.MAX_WBITS)

    def decode(self, chunk: bytes, max_bytes: int) -> tuple[bytes, bool]:
        """(decoded bytes, overflowed): never returns more than `max_bytes`."""
        if self.decompressor is None:
            return chunk[:max_bytes], len(chunk) > max_bytes
        try:
            piece = self.decompressor.decompress(chunk, max_bytes)
        except zlib.error:
            return b"", True  # corrupt stream: keep what we have, stop reading
        overflowed = bool(self.decompressor.unconsumed_tail)
        return piece, overflowed
