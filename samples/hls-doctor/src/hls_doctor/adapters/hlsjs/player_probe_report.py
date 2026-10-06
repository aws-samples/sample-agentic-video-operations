"""Typed view of the hls.js harness output: how a real player experienced it."""

from pydantic import BaseModel, Field


class PlayerEvent(BaseModel):
    name: str
    details: str | None = None
    fatal: bool | None = None
    level: int | None = None


class PlayerRequest(BaseModel):
    url: str
    method: str = "GET"
    status: int | None = None


class PlayerProbeReport(BaseModel):
    url: str
    events: list[PlayerEvent] = Field(default_factory=list)
    errors: list[PlayerEvent] = Field(default_factory=list)
    requests: list[PlayerRequest] = Field(default_factory=list)

    @property
    def fatal_errors(self) -> list[PlayerEvent]:
        return [event for event in self.errors if event.fatal]
