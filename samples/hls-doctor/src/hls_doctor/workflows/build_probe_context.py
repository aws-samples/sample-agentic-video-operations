"""Build the one injection seam every probe uses: live or fixture-replay ports."""

import time
from dataclasses import dataclass

from hls_doctor.adapters.applevalidator.replay_mediastreamvalidator import (
    create_replay_validator,
)
from hls_doctor.adapters.applevalidator.run_mediastreamvalidator import (
    create_live_validator,
)
from hls_doctor.adapters.applevalidator.validator_report import ValidateStream
from hls_doctor.adapters.ffprobe.locate_ffprobe import locate_ffprobe
from hls_doctor.adapters.ffprobe.probe_report import ProbeSegment
from hls_doctor.adapters.ffprobe.replay_ffprobe import create_replay_probe
from hls_doctor.adapters.ffprobe.run_ffprobe import create_live_probe
from hls_doctor.adapters.http.fetch_url import create_live_fetch
from hls_doctor.adapters.http.http_exchange import FetchUrl
from hls_doctor.adapters.http.replay_fetch_url import ReplayTimeline, create_replay_fetch
from hls_doctor.settings.runtime_settings import HlsDoctorSettings
from media_ops_contracts.tool_failure import ToolFailure


@dataclass(frozen=True)
class ProbeContext:
    fetch: FetchUrl
    timeline: ReplayTimeline | None
    demo: bool
    scenario: str | None
    settings: HlsDoctorSettings
    validator: ValidateStream | None = None

    def now_ms(self) -> int:
        if self.timeline is not None:
            return self.timeline.now_ms
        return int(time.monotonic() * 1000)

    def wait(self, seconds: float) -> None:
        if self.timeline is not None:
            self.timeline.wait(seconds)
        else:
            time.sleep(seconds)

    def media_probe(self) -> ProbeSegment | None:
        """The ffprobe port, or None when media probing is unavailable here."""
        if self.demo and self.scenario is not None:
            try:
                return create_replay_probe(self.settings.fixtures_dir, self.scenario)
            except ToolFailure:
                return None
        try:
            locate_ffprobe()
        except ToolFailure:
            return None
        return create_live_probe()


def build_probe_context(
    settings: HlsDoctorSettings,
    *,
    extra_headers: dict[str, str] | None = None,
    header_origin_url: str | None = None,
) -> ProbeContext:
    if settings.demo:
        timeline = ReplayTimeline()
        fetch = create_replay_fetch(settings.fixtures_dir, settings.demo_scenario, timeline)
        return ProbeContext(
            fetch=fetch,
            timeline=timeline,
            demo=True,
            scenario=settings.demo_scenario,
            settings=settings,
            validator=create_replay_validator(settings.fixtures_dir, settings.demo_scenario),
        )
    fetch = create_live_fetch(
        timeout_seconds=settings.hls_timeout_seconds,
        user_agent=settings.hls_user_agent,
        extra_headers=extra_headers,
        header_origin_url=header_origin_url,
        allow_private_targets=settings.hls_allow_private_targets,
    )
    return ProbeContext(
        fetch=fetch,
        timeline=None,
        demo=False,
        scenario=None,
        settings=settings,
        validator=create_live_validator(allow_private_targets=settings.hls_allow_private_targets),
    )
