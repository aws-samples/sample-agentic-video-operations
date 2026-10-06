"""Typed view of ffprobe JSON output for one media resource."""

from typing import Protocol

from pydantic import BaseModel, Field


class ProbedStream(BaseModel):
    index: int = 0
    codec_type: str | None = None
    codec_name: str | None = None
    profile: str | None = None
    width: int | None = None
    height: int | None = None
    avg_frame_rate: str | None = None
    sample_rate: str | None = None
    channels: int | None = None


class ProbedPacket(BaseModel):
    codec_type: str | None = None
    pts_time: float | None = None
    dts_time: float | None = None
    duration_time: float | None = None
    flags: str | None = None


class SegmentProbe(BaseModel):
    url: str
    available: bool = True
    unavailable_reason: str | None = None
    streams: list[ProbedStream] = Field(default_factory=list)
    packets: list[ProbedPacket] = Field(default_factory=list)
    container_format: str | None = None
    duration_seconds: float | None = None


class ProbeSegment(Protocol):
    """The media-probe port; live ffprobe and fixture replay implement it."""

    def __call__(self, url: str, *, with_packets: bool = False) -> SegmentProbe: ...


def parse_ffprobe_output(url: str, payload: dict) -> SegmentProbe:
    """Build the typed probe from `ffprobe -of json` output."""
    streams = [ProbedStream.model_validate(stream) for stream in payload.get("streams", [])]
    packets = [ProbedPacket.model_validate(coerce_packet(p)) for p in payload.get("packets", [])]
    format_block = payload.get("format", {})
    duration = format_block.get("duration")
    return SegmentProbe(
        url=url,
        streams=streams,
        packets=packets,
        container_format=format_block.get("format_name"),
        duration_seconds=float(duration) if duration is not None else None,
    )


def coerce_packet(packet: dict) -> dict:
    out = dict(packet)
    for key in ("pts_time", "dts_time", "duration_time"):
        if key in out and out[key] is not None:
            try:
                out[key] = float(out[key])
            except (TypeError, ValueError):
                out[key] = None
    return out
