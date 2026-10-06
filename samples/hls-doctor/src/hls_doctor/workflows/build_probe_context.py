"""Build the one injection seam every probe uses: live or fixture-replay ports."""

from dataclasses import dataclass

from hls_doctor.adapters.http.fetch_url import create_live_fetch
from hls_doctor.adapters.http.http_exchange import FetchUrl
from hls_doctor.adapters.http.replay_fetch_url import ReplayTimeline, create_replay_fetch
from hls_doctor.settings.runtime_settings import HlsDoctorSettings


@dataclass(frozen=True)
class ProbeContext:
    fetch: FetchUrl
    timeline: ReplayTimeline | None
    demo: bool
    scenario: str | None


def build_probe_context(
    settings: HlsDoctorSettings, *, extra_headers: dict[str, str] | None = None
) -> ProbeContext:
    if settings.demo:
        timeline = ReplayTimeline()
        fetch = create_replay_fetch(settings.fixtures_dir, settings.demo_scenario, timeline)
        return ProbeContext(
            fetch=fetch, timeline=timeline, demo=True, scenario=settings.demo_scenario
        )
    fetch = create_live_fetch(
        timeout_seconds=settings.hls_timeout_seconds,
        user_agent=settings.hls_user_agent,
        extra_headers=extra_headers,
    )
    return ProbeContext(fetch=fetch, timeline=None, demo=False, scenario=None)
