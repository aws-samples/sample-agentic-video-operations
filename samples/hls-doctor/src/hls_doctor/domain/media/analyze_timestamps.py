"""Timestamp continuity analysis over ffprobe packet output (spec §10 media).

ffprobe emits packets in decode (DTS) order, where presentation timestamps
legally run backwards whenever B-frames reorder the GOP. Continuity is
therefore judged on DTS; PTS is used only when a packet carries no DTS.
"""

from pydantic import BaseModel, Field

from hls_doctor.adapters.ffprobe.probe_report import SegmentProbe


class TimestampAnalysis(BaseModel):
    url: str
    packet_count: int = 0
    first_pts: float | None = None
    last_pts: float | None = None
    regressions: list[str] = Field(default_factory=list)
    clock: str = "dts"
    has_keyframe: bool = False


def analyze_timestamps(probe: SegmentProbe) -> TimestampAnalysis:
    analysis = TimestampAnalysis(url=probe.url)
    if any(packet.dts_time is None for packet in probe.packets):
        analysis.clock = "pts"  # no decode clock recorded; fall back to presentation
    previous: float | None = None
    for packet in probe.packets:
        value = packet.dts_time if analysis.clock == "dts" else packet.pts_time
        if value is None:
            continue
        analysis.packet_count += 1
        if packet.pts_time is not None:
            if analysis.first_pts is None:
                analysis.first_pts = packet.pts_time
            analysis.last_pts = packet.pts_time
        if packet.flags and packet.flags.startswith("K"):
            analysis.has_keyframe = True
        if previous is not None and value < previous:
            analysis.regressions.append(f"{analysis.clock}_time {value:.3f} after {previous:.3f}")
        previous = value
    return analysis
