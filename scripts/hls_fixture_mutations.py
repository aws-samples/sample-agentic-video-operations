"""Deterministic fault injections for HLS Doctor fixture scenarios.

Each mutation is a pure function over a scenario's fixture files (a dict of
file stem to parsed JSON). `scripts/mutate_hls_fixtures.py` applies one to its
base scenario and writes the derived scenario, so every broken stream in
`fixtures/` is provenance-traceable to a base recording plus one named mutation.
"""

import copy
import json
from collections.abc import Callable
from typing import Any

ScenarioFiles = dict[str, Any]
Mutation = Callable[[ScenarioFiles], ScenarioFiles]

HTTP = "http.exchanges"
FFPROBE = "ffprobe.probe_segment"

NOT_FOUND_BODY = "<html><body><h1>404 Not Found</h1></body></html>"
EXPIRED_TOKEN_BODY = (
    '<?xml version="1.0"?><Error><Code>AccessDenied</Code>'  # noqa: S105 - error body, no secret
    "<Message>Request has expired</Message></Error>"
)


def _exchanges(files: ScenarioFiles) -> dict[str, Any]:
    return files[HTTP]["exchanges"]


def _playlists(files: ScenarioFiles) -> dict[str, Any]:
    return {
        url: entry
        for url, entry in _exchanges(files).items()
        if url.endswith(".m3u8") and "body" in entry
    }


def _playlists_with_sequence(files: ScenarioFiles) -> dict[str, Any]:
    return {
        url: entry
        for url, entry in _exchanges(files).items()
        if url.endswith(".m3u8") and "sequence" in entry
    }


def _not_found(entry: dict[str, Any]) -> None:
    entry.clear()
    entry.update(
        {
            "status": 404,
            "headers": {"content-type": "text/html", "server": "demo-cdn"},
            "body": NOT_FOUND_BODY,
        }
    )


def _edit_body(entry: dict[str, Any], old: str, new: str) -> None:
    if old not in entry["body"]:
        raise ValueError(f"mutation target {old!r} not present in the base body")
    entry["body"] = entry["body"].replace(old, new)


def missing_variant(files: ScenarioFiles) -> ScenarioFiles:
    """The lowest ABR variant's media playlist returns 404."""
    mutated = copy.deepcopy(files)
    url = next(url for url in _playlists(mutated) if "/v480/" in url)
    _not_found(_exchanges(mutated)[url])
    return mutated


def wrong_version(files: ScenarioFiles) -> ScenarioFiles:
    """The 1080p playlist declares EXT-X-VERSION:3 while using v6 EXT-X-MAP syntax."""
    mutated = copy.deepcopy(files)
    url = next(url for url in _playlists(mutated) if "/v1080/" in url)
    _edit_body(_exchanges(mutated)[url], "#EXT-X-VERSION:7", "#EXT-X-VERSION:3")
    return mutated


def targetduration_exceeded(files: ScenarioFiles) -> ScenarioFiles:
    """One 1080p segment advertises 8.5 s against TARGETDURATION 6."""
    mutated = copy.deepcopy(files)
    url = next(url for url in _playlists(mutated) if "/v1080/" in url)
    _edit_body(_exchanges(mutated)[url], "#EXTINF:6.00000,\nseg3.m4s", "#EXTINF:8.50000,\nseg3.m4s")
    return mutated


def broken_map(files: ScenarioFiles) -> ScenarioFiles:
    """The 1080p initialization section returns 404."""
    mutated = copy.deepcopy(files)
    url = next(url for url in _exchanges(mutated) if "/v1080/init.mp4" in url)
    _not_found(_exchanges(mutated)[url])
    return mutated


def expired_key(files: ScenarioFiles) -> ScenarioFiles:
    """The content key URL returns 403 with an expiry-shaped error body."""
    mutated = copy.deepcopy(files)
    url = next(url for url in _exchanges(mutated) if url.endswith("content.key"))
    entry = _exchanges(mutated)[url]
    entry.clear()
    entry.update(
        {
            "status": 403,
            "headers": {"content-type": "application/xml", "server": "demo-cdn"},
            "body": EXPIRED_TOKEN_BODY,
        }
    )
    return mutated


def subtitle_playlist_404(files: ScenarioFiles) -> ScenarioFiles:
    """The English subtitle rendition playlist returns 404."""
    mutated = copy.deepcopy(files)
    url = next(url for url in _exchanges(mutated) if "/subs/en/prog.m3u8" in url)
    _not_found(_exchanges(mutated)[url])
    return mutated


def segment_race(files: ScenarioFiles) -> ScenarioFiles:
    """A newly advertised segment 404s twice before appearing, on two renditions."""
    mutated = copy.deepcopy(files)
    for prefix, offsets in (("v1080", (2600, 3000, 3940)), ("v720", (2650, 3050, 3990))):
        url = next(url for url in _exchanges(mutated) if f"/{prefix}/seg18423.m4s" in url)
        available = dict(_exchanges(mutated)[url])
        _exchanges(mutated)[url] = {
            "sequence": [
                {"at_ms": offsets[0], "status": 404,
                 "headers": {"content-type": "text/html", "server": "demo-cdn"}},
                {"at_ms": offsets[1], "status": 404,
                 "headers": {"content-type": "text/html", "server": "demo-cdn"}},
                {"at_ms": offsets[2], **available},
            ]
        }  # fmt: skip
    return mutated


def frozen_playlist(files: ScenarioFiles) -> ScenarioFiles:
    """The 1080p playlist stops advancing for longer than two target durations."""
    mutated = copy.deepcopy(files)
    url = next(url for url in _playlists_with_sequence(mutated) if "/v1080/" in url)
    sequence = _exchanges(mutated)[url]["sequence"]
    frozen_body = sequence[0]["body"]
    _exchanges(mutated)[url]["sequence"] = [
        {**sequence[0], "at_ms": at, "body": frozen_body} for at in (0, 500, 6500, 12500)
    ]
    return mutated


def stale_cdn_manifest(files: ScenarioFiles) -> ScenarioFiles:
    """The CDN keeps serving one old playlist generation with a growing Age."""
    mutated = frozen_playlist(files)
    url = next(url for url in _playlists_with_sequence(mutated) if "/v1080/" in url)
    for index, entry in enumerate(_exchanges(mutated)[url]["sequence"]):
        entry["headers"] = {
            **entry["headers"],
            "age": str(30 + 6 * index),
            "etag": '"gen-18416"',
        }
    return mutated


def signaled_gap(files: ScenarioFiles) -> ScenarioFiles:
    """A missing 1080p segment is correctly declared with EXT-X-GAP."""
    mutated = copy.deepcopy(files)
    playlist_url = next(url for url in _playlists_with_sequence(mutated) if "/v1080/" in url)
    first = _exchanges(mutated)[playlist_url]["sequence"][0]
    first["body"] = (
        first["body"]
        .replace("#EXTINF:6.00000,\nseg18418.m4s", "#EXT-X-GAP\n#EXTINF:6.00000,\nseg18418.m4s")
        .replace("#EXT-X-VERSION:7", "#EXT-X-VERSION:8")
    )
    segment_url = next(url for url in _exchanges(mutated) if "/v1080/seg18418.m4s" in url)
    _not_found(_exchanges(mutated)[segment_url])
    return mutated


def pts_regression(files: ScenarioFiles) -> ScenarioFiles:
    """The last probed 1080p segment's decode clock regresses mid-segment."""
    mutated = copy.deepcopy(files)
    base = "https://demo.example/vod/v1080"
    normal = [
        {"codec_type": "video", "pts_time": f"{index * 0.0333:.4f}",
         "dts_time": f"{index * 0.0333:.4f}", "flags": "K__" if index == 0 else "___"}
        for index in range(12)
    ]  # fmt: skip
    broken = copy.deepcopy(normal)
    for index in range(6, 12):
        broken[index]["pts_time"] = f"{(index - 6) * 0.0333:.4f}"
        broken[index]["dts_time"] = f"{(index - 6) * 0.0333:.4f}"
    streams = [{
        "index": 0, "codec_type": "video", "codec_name": "h264", "profile": "High",
        "width": 1920, "height": 1080, "avg_frame_rate": "30000/1001",
    }]  # fmt: skip
    mutated[FFPROBE] = {
        f"{base}/seg0.m4s": {"streams": streams, "packets": normal,
                             "format": {"format_name": "mov,mp4,m4a", "duration": "6.0"}},
        f"{base}/seg5.m4s": {"streams": streams, "packets": broken,
                             "format": {"format_name": "mov,mp4,m4a", "duration": "6.0"}},
    }  # fmt: skip
    return mutated


SPLICE_INSERT_60S_B64 = "/DAvAAAAAAAA///wFAVIAACPf+/+c2nALv4AUsz1AAAAAAAKAAhDVUVJAAABNWLbowo="
INTERSTITIAL_TAG = (
    '#EXT-X-DATERANGE:ID="mid-1",CLASS="com.apple.hls.interstitial",'
    'START-DATE="2026-10-06T14:01:00.000Z",DURATION=15.0,'
    'X-ASSET-LIST="https://demo.example/live/ads/list.json"'
)
COMPATIBLE_ASSET_BODY = (
    "#EXTM3U\n#EXT-X-VERSION:7\n"
    '#EXT-X-STREAM-INF:BANDWIDTH=2000000,CODECS="avc1.640020,mp4a.40.2",'
    "RESOLUTION=1280x720\nspot/v720.m3u8\n"
)
INCOMPATIBLE_ASSET_BODY = (
    "#EXTM3U\n#EXT-X-VERSION:7\n"
    '#EXT-X-STREAM-INF:BANDWIDTH=2000000,CODECS="mp4v.20.9,mp4a.40.2",'
    "RESOLUTION=1280x720\nspot/v720.m3u8\n"
)


def _shift_program_date_times(body: str, seconds: float) -> str:
    import re
    from datetime import datetime, timedelta

    def shift(match: "re.Match[str]") -> str:
        stamp = datetime.fromisoformat(match.group(1).replace("Z", "+00:00"))
        shifted = stamp + timedelta(seconds=seconds)
        return (
            "#EXT-X-PROGRAM-DATE-TIME:"
            + shifted.strftime("%Y-%m-%dT%H:%M:%S.")
            + (f"{shifted.microsecond // 1000:03d}Z")
        )

    return re.sub(r"#EXT-X-PROGRAM-DATE-TIME:([0-9T:.\-]+Z)", shift, body)


def audio_drift(files: ScenarioFiles) -> ScenarioFiles:
    """The audio rendition's program clock trails video by 2.1 seconds."""
    mutated = copy.deepcopy(files)
    url = next(url for url in _playlists_with_sequence(mutated) if "/audio/" in url)
    for entry in _exchanges(mutated)[url]["sequence"]:
        entry["body"] = _shift_program_date_times(entry["body"], -2.1)
    return mutated


def missing_discontinuity(files: ScenarioFiles) -> ScenarioFiles:
    """The probed 1080p segments change codec with no discontinuity declared."""
    mutated = copy.deepcopy(files)
    base = "https://demo.example/live/v1080"
    h264 = [
        {"index": 0, "codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080}
    ]
    hevc = [
        {"index": 0, "codec_type": "video", "codec_name": "hevc", "width": 1920, "height": 1080}
    ]
    packets = [{"codec_type": "video", "pts_time": f"{i * 0.0333:.4f}"} for i in range(6)]
    mutated[FFPROBE] = {
        f"{base}/seg18416.m4s": {
            "streams": h264,
            "packets": packets,
            "format": {"format_name": "mov,mp4,m4a"},
        },
        f"{base}/seg18421.m4s": {
            "streams": hevc,
            "packets": packets,
            "format": {"format_name": "mov,mp4,m4a"},
        },
    }
    return mutated


def cueout_without_cuein(files: ScenarioFiles) -> ScenarioFiles:
    """An ad break opens with CUE-OUT and never returns to the program."""
    mutated = copy.deepcopy(files)
    url = next(url for url in _playlists_with_sequence(mutated) if "/v1080/" in url)
    first = _exchanges(mutated)[url]["sequence"][0]
    first["body"] = first["body"].replace(
        "#EXTINF:6.00000,\nseg18419.m4s",
        "#EXT-X-CUE-OUT:DURATION=30.0\n#EXTINF:6.00000,\nseg18419.m4s",
    )
    return mutated


def scte35_duration_mismatch(files: ScenarioFiles) -> ScenarioFiles:
    """The DATERANGE duration disagrees with its decoded SCTE-35 payload."""
    import base64 as b64

    mutated = copy.deepcopy(files)
    payload_hex = "0x" + b64.b64decode(SPLICE_INSERT_60S_B64).hex().upper()
    daterange = (
        '#EXT-X-DATERANGE:ID="break-1",START-DATE="2026-10-06T14:00:30.000Z",'
        'END-DATE="2026-10-06T14:01:00.000Z",DURATION=30.0,'
        f"SCTE35-OUT={payload_hex}"
    )
    for prefix in ("v1080", "v720", "audio"):
        url = next(u for u in _playlists_with_sequence(mutated) if f"/{prefix}/" in u)
        for entry in _exchanges(mutated)[url]["sequence"]:
            entry["body"] = entry["body"].replace(
                '#EXT-X-MAP:URI="init.mp4"', '#EXT-X-MAP:URI="init.mp4"\n' + daterange
            )
    return mutated


def _inject_interstitial(files: ScenarioFiles, prefixes: tuple[str, ...]) -> ScenarioFiles:
    mutated = copy.deepcopy(files)
    for prefix in prefixes:
        url = next(u for u in _playlists_with_sequence(mutated) if f"/{prefix}/" in u)
        for entry in _exchanges(mutated)[url]["sequence"]:
            entry["body"] = entry["body"].replace(
                '#EXT-X-MAP:URI="init.mp4"',
                '#EXT-X-MAP:URI="init.mp4"\n' + INTERSTITIAL_TAG,
            )
    return mutated


def interstitial_asset_404(files: ScenarioFiles) -> ScenarioFiles:
    """The interstitial's X-ASSET-LIST URL returns 404."""
    mutated = _inject_interstitial(files, ("v1080", "v720", "audio"))
    _exchanges(mutated)["https://demo.example/live/ads/list.json"] = {
        "status": 404,
        "headers": {"content-type": "text/html", "server": "demo-cdn"},
        "body": NOT_FOUND_BODY,
    }
    return mutated


def _asset_list_entries(asset_body: str) -> dict[str, Any]:
    return {
        "https://demo.example/live/ads/list.json": {
            "status": 200,
            "headers": {"content-type": "application/json", "server": "demo-cdn"},
            "body": json.dumps(
                {"ASSETS": [{"URI": "https://demo.example/live/ads/spot.m3u8", "DURATION": 15.0}]}
            ),
        },
        "https://demo.example/live/ads/spot.m3u8": {
            "status": 200,
            "headers": {"content-type": "application/vnd.apple.mpegurl", "server": "demo-cdn"},
            "body": asset_body,
        },
    }


def interstitial_bad_asset(files: ScenarioFiles) -> ScenarioFiles:
    """The interstitial asset declares a codec the primary clients cannot play."""
    mutated = _inject_interstitial(files, ("v1080", "v720", "audio"))
    _exchanges(mutated).update(_asset_list_entries(INCOMPATIBLE_ASSET_BODY))
    return mutated


def interstitial_rendition_mismatch(files: ScenarioFiles) -> ScenarioFiles:
    """The interstitial event is signaled in video but missing from audio."""
    mutated = _inject_interstitial(files, ("v1080", "v720"))
    _exchanges(mutated).update(_asset_list_entries(COMPATIBLE_ASSET_BODY))
    return mutated


def variant_lag(files: ScenarioFiles) -> ScenarioFiles:
    """The 720p variant publishes two segments behind its peers."""
    mutated = copy.deepcopy(files)
    url = next(u for u in _playlists_with_sequence(mutated) if "/v720/" in u)
    for entry in _exchanges(mutated)[url]["sequence"]:
        body = entry["body"]
        for msn in range(18410, 18428):
            body = body.replace(f"seg{msn}.m4s", f"seg{msn - 2}.m4s")
        body = body.replace("#EXT-X-MEDIA-SEQUENCE:184", "#EXT-X-MEDIA-SEQUENCE:LAG184")
        import re as _re

        body = _re.sub(
            r"#EXT-X-MEDIA-SEQUENCE:LAG(\d+)",
            lambda m: f"#EXT-X-MEDIA-SEQUENCE:{int(m.group(1)) - 2}",
            body,
        )
        entry["body"] = body
    for msn in (18414, 18415):
        source = dict(_exchanges(mutated)["https://demo.example/live/v720/seg18416.m4s"])
        _exchanges(mutated)[f"https://demo.example/live/v720/seg{msn}.m4s"] = source
    return mutated


def llhls_blocking_reload(files: ScenarioFiles) -> ScenarioFiles:
    """The _HLS_msn blocking reload answers with a stale playlist generation."""
    mutated = copy.deepcopy(files)
    for prefix in ("v1080", "v720"):
        stale = dict(_exchanges(mutated)[f"https://demo.example/llhls/{prefix}/prog.m3u8"])
        _exchanges(mutated)[f"https://demo.example/llhls/{prefix}/prog.m3u8?_HLS_msn=304"] = stale
    return mutated


def stale_rendition_report(files: ScenarioFiles) -> ScenarioFiles:
    """RENDITION-REPORT lags the actual rendition by more than three segments."""
    mutated = copy.deepcopy(files)
    for prefix in ("v1080", "v720"):
        url = f"https://demo.example/llhls/{prefix}/prog.m3u8"
        entry = _exchanges(mutated)[url]
        entry["body"] = entry["body"].replace("LAST-MSN=303", "LAST-MSN=299")
    return mutated


def preload_hint_404(files: ScenarioFiles) -> ScenarioFiles:
    """The hinted part keeps returning 404 for the whole probe window."""
    mutated = copy.deepcopy(files)
    for prefix in ("v1080", "v720"):
        url = f"https://demo.example/llhls/{prefix}/seg304.part2.m4s"
        _not_found(_exchanges(mutated)[url])
    return mutated


def steering_pathway_failure(files: ScenarioFiles) -> ScenarioFiles:
    """Pathway B's representative variant fails while pathway A stays healthy."""
    mutated = copy.deepcopy(files)
    master_url = "https://demo.example/vod/master.m3u8"
    master = _exchanges(mutated)[master_url]
    body = master["body"].replace(
        "#EXT-X-INDEPENDENT-SEGMENTS",
        "#EXT-X-INDEPENDENT-SEGMENTS\n"
        '#EXT-X-CONTENT-STEERING:SERVER-URI="steering.json",PATHWAY-ID="A"',
    )
    body = body.replace("#EXT-X-STREAM-INF:", '#EXT-X-STREAM-INF:PATHWAY-ID="A",')
    body += (
        '#EXT-X-STREAM-INF:PATHWAY-ID="B",BANDWIDTH=6000000,'
        'CODECS="avc1.640028,mp4a.40.2",RESOLUTION=1920x1080,FRAME-RATE=29.970\n'
        "b/v1080/prog.m3u8\n"
    )
    master["body"] = body
    _exchanges(mutated)["https://demo.example/vod/steering.json"] = {
        "status": 200,
        "headers": {"content-type": "application/json", "server": "demo-cdn"},
        "body": json.dumps(
            {
                "VERSION": 1,
                "TTL": 300,
                "RELOAD-URI": "steering.json",
                "PATHWAY-PRIORITY": ["A", "B"],
            }
        ),
    }
    _exchanges(mutated)["https://demo.example/vod/b/v1080/prog.m3u8"] = {
        "status": 503,
        "headers": {"content-type": "text/html", "server": "demo-cdn"},
        "body": "<html><body><h1>503 Service Unavailable</h1></body></html>",
    }
    return mutated


MUTATIONS: dict[str, tuple[str, Mutation]] = {
    "hls_missing_variant": ("hls_clean_vod", missing_variant),
    "hls_wrong_version": ("hls_clean_vod", wrong_version),
    "hls_targetduration_exceeded": ("hls_clean_vod", targetduration_exceeded),
    "hls_broken_map": ("hls_clean_vod", broken_map),
    "hls_expired_key": ("hls_clean_vod", expired_key),
    "hls_subtitle_playlist_404": ("hls_clean_vod", subtitle_playlist_404),
    "hls_pts_regression": ("hls_clean_vod", pts_regression),
    "hls_segment_race": ("hls_clean_live", segment_race),
    "hls_frozen_playlist": ("hls_clean_live", frozen_playlist),
    "hls_stale_cdn_manifest": ("hls_clean_live", stale_cdn_manifest),
    "hls_signaled_gap": ("hls_clean_live", signaled_gap),
    "hls_audio_drift": ("hls_clean_live", audio_drift),
    "hls_missing_discontinuity": ("hls_clean_live", missing_discontinuity),
    "hls_cueout_without_cuein": ("hls_clean_live", cueout_without_cuein),
    "hls_scte35_duration_mismatch": ("hls_clean_live", scte35_duration_mismatch),
    "hls_interstitial_asset_404": ("hls_clean_live", interstitial_asset_404),
    "hls_interstitial_bad_asset": ("hls_clean_live", interstitial_bad_asset),
    "hls_interstitial_rendition_mismatch": ("hls_clean_live", interstitial_rendition_mismatch),
    "hls_variant_lag": ("hls_clean_live", variant_lag),
    "hls_llhls_blocking_reload": ("hls_clean_llhls", llhls_blocking_reload),
    "hls_stale_rendition_report": ("hls_clean_llhls", stale_rendition_report),
    "hls_preload_hint_404": ("hls_clean_llhls", preload_hint_404),
    "hls_steering_pathway_failure": ("hls_clean_vod", steering_pathway_failure),
}


def apply_mutation(files: ScenarioFiles, name: str) -> ScenarioFiles:
    if name not in MUTATIONS:
        known = ", ".join(sorted(MUTATIONS))
        raise SystemExit(f"Unknown mutation {name!r}. Known mutations: {known}")
    return MUTATIONS[name][1](files)


def dump_fixture(fixture: dict[str, Any]) -> str:
    return json.dumps(fixture, indent=1) + "\n"
