"""Live media probe: ffprobe over one URL, JSON output, fixed argv."""

import json
import subprocess

from hls_doctor.adapters.ffprobe.locate_ffprobe import locate_ffprobe
from hls_doctor.adapters.ffprobe.probe_report import (
    ProbeSegment,
    SegmentProbe,
    parse_ffprobe_output,
)

PROBE_TIMEOUT_SECONDS = 60


def create_live_probe() -> ProbeSegment:
    """A ProbeSegment backed by the local ffprobe binary."""

    def probe(url: str, *, with_packets: bool = False) -> SegmentProbe:
        binary = locate_ffprobe()
        argv = [binary, "-v", "error", "-show_streams", "-show_format", "-of", "json"]
        if with_packets:
            argv += ["-show_packets", "-select_streams", "v:0"]
        argv.append(url)
        completed = subprocess.run(
            argv, capture_output=True, text=True, timeout=PROBE_TIMEOUT_SECONDS, check=False
        )
        if completed.returncode != 0:
            return SegmentProbe(
                url=url,
                available=False,
                unavailable_reason=completed.stderr.strip().splitlines()[-1][:200]
                if completed.stderr.strip()
                else f"ffprobe exited with {completed.returncode}",
            )
        return parse_ffprobe_output(url, json.loads(completed.stdout or "{}"))

    return probe
