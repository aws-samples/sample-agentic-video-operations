"""One observed HTTP exchange: the unit of delivery evidence (spec §18)."""

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


class FetchUrl(Protocol):
    """The fetch port every probe uses; live and replay implementations match it."""

    def __call__(self, url: str, *, range_header: str | None = None) -> HttpExchange: ...
