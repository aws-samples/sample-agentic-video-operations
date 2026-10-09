from pathlib import Path

import pytest

from hls_doctor.adapters.http.classify_http_error import require_usable_entry_url
from hls_doctor.adapters.http.redact_url import redact_url
from hls_doctor.adapters.http.replay_fetch_url import ReplayTimeline, create_replay_fetch
from media_ops_contracts.tool_failure import ToolFailure

FIXTURES_DIR = Path(__file__).resolve().parents[4] / "fixtures"


def test_entry_url_scheme_is_validated() -> None:
    with pytest.raises(ToolFailure) as failure:
        require_usable_entry_url("ftp://demo.example/x.m3u8")
    assert failure.value.kind.value == "InvalidRequest"


def test_redact_masks_every_query_value_except_delivery_directives() -> None:
    url = "https://demo.example/seg.ts?hdnts=exp~hmac&start=5&_HLS_msn=304"
    redacted = redact_url(url)
    assert redacted == "https://demo.example/seg.ts?hdnts=REDACTED&start=REDACTED&_HLS_msn=304"
    assert redact_url("https://demo.example/seg.ts") == "https://demo.example/seg.ts"


def test_replay_fails_closed_on_unknown_url() -> None:
    fetch = create_replay_fetch(FIXTURES_DIR, "hls_clean_vod", ReplayTimeline())
    with pytest.raises(ToolFailure) as failure:
        fetch("https://demo.example/not-recorded.m3u8")
    assert "No recorded exchange" in failure.value.message


def test_replay_answers_recorded_urls_and_advances_the_clock() -> None:
    timeline = ReplayTimeline()
    fetch = create_replay_fetch(FIXTURES_DIR, "hls_clean_vod", timeline)
    exchange = fetch("https://demo.example/vod/master.m3u8")
    assert exchange.ok and exchange.body_text is not None
    assert exchange.body_text.startswith("#EXTM3U")
    timeline.wait(2.5)
    assert timeline.now_ms >= 2500
