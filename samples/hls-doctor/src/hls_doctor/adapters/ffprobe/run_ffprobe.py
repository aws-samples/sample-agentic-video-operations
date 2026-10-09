"""Live media probe: ffprobe over local bytes only, fixed argv.

ffprobe never touches the network: every caller downloads through the guarded
fetcher first and probes the temp file. "Local bytes only" is a property of
this adapter - any target that is not the workflow's own temp download
(network URLs included, and ffmpeg pseudo-protocols like `concat:`,
`subfile,...:`, `data:`) is refused before ffprobe sees it.
"""

import json
import subprocess
import tempfile
from pathlib import Path

from hls_doctor.adapters.ffprobe.locate_ffprobe import locate_ffprobe
from hls_doctor.adapters.ffprobe.probe_report import (
    ProbeSegment,
    SegmentProbe,
    parse_ffprobe_output,
)
from media_ops_contracts.tool_failure import FailureKind, ToolFailure

PROBE_TIMEOUT_SECONDS = 60


def create_live_probe() -> ProbeSegment:
    """A ProbeSegment backed by the local ffprobe binary."""

    def probe(url: str, *, with_packets: bool = False) -> SegmentProbe:
        binary = locate_ffprobe()
        argv = [binary, "-v", "error", "-protocol_whitelist", protocol_whitelist(url),
                "-show_streams", "-show_format", "-of", "json"]  # fmt: skip
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


def protocol_whitelist(target: str) -> str:
    """`file`, and only for the workflow's own temp download; nothing else.

    An allowlist, not a blocklist: the target must resolve to an existing
    hls-doctor media temp file inside the system temp directory. Network URLs
    are refused here too - downloading is the guarded fetcher's job, and
    ffprobe only ever sees local bytes.
    """
    resolved = Path(target).resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    is_own_download = (
        resolved.is_file()
        and resolved.name.startswith("hls-doctor-media-")
        and temp_root in resolved.parents
    )
    if not is_own_download:
        raise ToolFailure(
            FailureKind.INVALID_REQUEST,
            f"Refusing to probe {target[:80]!r}: ffprobe reads local bytes only -"
            " the workflow downloads through the guarded fetcher first.",
            "Pass an http or https segment URL to probe_segment; it downloads"
            " and probes the bytes for you.",
        )
    return "file"
