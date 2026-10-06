"""Timestamp continuity analysis over ffprobe packet output (spec §10 media)."""

from pydantic import BaseModel, Field

from hls_doctor.adapters.ffprobe.probe_report import SegmentProbe


class TimestampAnalysis(BaseModel):
    url: str
    packet_count: int = 0
    first_pts: float | None = None
    last_pts: float | None = None
    regressions: list[str] = Field(default_factory=list)
    has_keyframe: bool = False


def analyze_timestamps(probe: SegmentProbe) -> TimestampAnalysis:
    analysis = TimestampAnalysis(url=probe.url)
    previous_pts: float | None = None
    for packet in probe.packets:
        if packet.pts_time is None:
            continue
        analysis.packet_count += 1
        if analysis.first_pts is None:
            analysis.first_pts = packet.pts_time
        analysis.last_pts = packet.pts_time
        if packet.flags and packet.flags.startswith("K"):
            analysis.has_keyframe = True
        if previous_pts is not None and packet.pts_time < previous_pts:
            analysis.regressions.append(f"pts_time {packet.pts_time:.3f} after {previous_pts:.3f}")
        previous_pts = packet.pts_time
    return analysis
