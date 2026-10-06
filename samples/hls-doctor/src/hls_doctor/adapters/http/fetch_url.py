"""Live HTTP fetch: one GET, timings and headers captured, errors become evidence."""

import base64
import time
from collections.abc import Callable
from datetime import UTC, datetime

import httpx

from hls_doctor.adapters.http.http_exchange import FetchUrl, HttpExchange

TEXT_CONTENT_MARKERS = ("mpegurl", "text", "json", "xml")
MAX_BODY_BYTES = 4_000_000


def create_live_fetch(
    *,
    timeout_seconds: float,
    user_agent: str,
    extra_headers: dict[str, str] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> FetchUrl:
    """A FetchUrl backed by httpx; transport errors are recorded, not raised."""
    client = httpx.Client(
        timeout=timeout_seconds,
        headers={"User-Agent": user_agent, **(extra_headers or {})},
        follow_redirects=True,
    )
    read_now = clock or (lambda: datetime.now(UTC))
    epoch = read_now()

    def fetch(url: str, *, range_header: str | None = None) -> HttpExchange:
        at_ms = int((read_now() - epoch).total_seconds() * 1000)
        headers = {"Range": range_header} if range_header else {}
        started = time.monotonic()
        try:
            response = client.get(url, headers=headers)
        except httpx.HTTPError as error:
            return HttpExchange(
                url=url,
                requested_url=url,
                at_ms=at_ms,
                transport_error=type(error).__name__,
                total_ms=(time.monotonic() - started) * 1000,
            )
        return build_exchange(url, response, at_ms, started)

    return fetch


def build_exchange(url: str, response: httpx.Response, at_ms: int, started: float) -> HttpExchange:
    total_ms = (time.monotonic() - started) * 1000
    body = response.content[:MAX_BODY_BYTES]
    content_type = response.headers.get("content-type", "").lower()
    is_text = any(marker in content_type for marker in TEXT_CONTENT_MARKERS)
    return HttpExchange(
        url=str(response.url),
        requested_url=url,
        at_ms=at_ms,
        status=response.status_code,
        headers=dict(response.headers),
        body_text=body.decode("utf-8", errors="replace") if is_text else None,
        body_bytes_b64=None if is_text else base64.b64encode(body).decode(),
        body_truncated=len(response.content) > MAX_BODY_BYTES,
        content_length=len(response.content),
        ttfb_ms=response.elapsed.total_seconds() * 1000,
        total_ms=total_ms,
        redirects=[str(item.url) for item in response.history],
    )
