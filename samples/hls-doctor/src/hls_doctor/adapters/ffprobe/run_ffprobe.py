"""Live media probe: ffprobe with an explicit protocol whitelist, fixed argv.

Network targets may only use http/https (tcp/tls beneath them); a local path -
the temp file the workflow just downloaded - may only use `file`. Everything
else (`file:` URLs, `concat:`, `data:`, `subfile:`, bare devices) is refused
before ffprobe sees it, rather than relying on ffmpeg's own checks.
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
    """http(s) for URLs; `file` only for the workflow's own temp download.

    Local input is an allowlist, not a blocklist: the path must resolve to an
    hls-doctor media temp file inside the system temp directory, so ffmpeg
    pseudo-protocols (`concat:`, `subfile,...:`, `data:`) and arbitrary paths
    never reach ffprobe.
    """
    if target.lower().startswith(("http://", "https://")):
        return "http,https,tcp,tls"
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
            f"Refusing to probe {target[:80]!r}: only http(s) URLs and the"
            " workflow's own downloaded bytes are probed.",
            "Pass an http or https segment URL.",
        )
    return "file"
