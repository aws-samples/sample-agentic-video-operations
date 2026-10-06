"""One observed HTTP exchange: the unit of delivery evidence (spec §18)."""

import base64
import hashlib
from typing import Protocol

from pydantic import BaseModel, Field


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

    def with_preview(self, preview_bytes: int = 1024) -> "HttpExchange":
        """A copy safe to store or return: body cut to a preview, hash retained."""
        updates: dict[str, object] = {}
        if self.body_text is not None and len(self.body_text) > preview_bytes:
            digest = hashlib.sha256(self.body_text.encode()).hexdigest()
            updates = {
                "body_text": self.body_text[:preview_bytes],
                "body_truncated": True,
                "body_sha256": digest,
            }
        elif self.body_bytes_b64 is not None:
            raw = base64.b64decode(self.body_bytes_b64)
            if len(raw) > preview_bytes:
                updates = {
                    "body_bytes_b64": base64.b64encode(raw[:preview_bytes]).decode(),
                    "body_truncated": True,
                    "body_sha256": hashlib.sha256(raw).hexdigest(),
                }
        return self.model_copy(update=updates) if updates else self


class FetchUrl(Protocol):
    """The fetch port every probe uses; live and replay implementations match it."""

    def __call__(self, url: str, *, range_header: str | None = None) -> HttpExchange: ...
