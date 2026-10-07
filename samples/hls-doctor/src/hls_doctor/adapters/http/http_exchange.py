"""One observed HTTP exchange: the unit of delivery evidence (spec §18)."""

import base64
import hashlib
from typing import Protocol

from pydantic import BaseModel, Field

from hls_doctor.adapters.http.redact_url import redact_playlist_body, redact_url

# Response headers that may appear in evidence; everything else is dropped.
# Set-Cookie, Authorization, Cookie and x-amz-* never pass this list.
HEADER_ALLOWLIST = frozenset(
    {
        "accept-ranges", "age", "cache-control", "content-encoding", "content-length",
        "content-range", "content-type", "date", "etag", "expires", "last-modified",
        "location", "server", "vary", "via", "x-cache", "cf-cache-status",
    }
)  # fmt: skip


class HttpExchange(BaseModel):
    """What one request observed. A 404 here is evidence, never an exception."""

    url: str
    requested_url: str
    at_ms: int
    status: int | None = None
    transport_error: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    body_text: str | None = None
    body_bytes_b64: str | None = None
    body_truncated: bool = False
    body_sha256: str | None = None
    content_length: int | None = None
    ttfb_ms: float | None = None
    total_ms: float | None = None
    redirects: list[str] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.transport_error is None and self.status is not None and self.status < 400

    def header(self, name: str) -> str | None:
        lowered = {key.lower(): value for key, value in self.headers.items()}
        return lowered.get(name.lower())

    def sanitized(self, preview_bytes: int = 1024, *, drop_body: bool = False) -> "HttpExchange":
        """The only form that may leave the process: redacted URLs, allowlisted
        headers, and a hashed body preview (or no body at all for key material)."""
        updates: dict[str, object] = {
            "url": redact_url(self.url),
            "requested_url": redact_url(self.requested_url),
            "redirects": [redact_url(hop) for hop in self.redirects],
            "headers": {
                name: value
                for name, value in self.headers.items()
                if name.lower() in HEADER_ALLOWLIST
            },
        }
        updates.update(self.body_policy(0 if drop_body else preview_bytes))
        return self.model_copy(update=updates)

    def body_policy(self, preview_bytes: int) -> dict[str, object]:
        if self.body_text is not None:
            redacted = redact_playlist_body(self.body_text)
            if len(redacted) > preview_bytes or redacted != self.body_text:
                return {
                    "body_text": redacted[:preview_bytes] or None,
                    "body_truncated": self.body_truncated or len(redacted) > preview_bytes,
                    "body_sha256": hashlib.sha256(self.body_text.encode()).hexdigest(),
                }
        if self.body_bytes_b64 is not None:
            # Binary bodies never leave the process: length and hash only.
            raw = base64.b64decode(self.body_bytes_b64)
            return {
                "body_bytes_b64": None,
                "body_truncated": True,
                "body_sha256": hashlib.sha256(raw).hexdigest(),
            }
        return {}


class FetchUrl(Protocol):
    """The fetch port every probe uses; live and replay implementations match it."""

    def __call__(self, url: str, *, range_header: str | None = None) -> HttpExchange: ...
