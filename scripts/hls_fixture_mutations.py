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
    """The 1080p playlist declares EXT-X-VERSION:3 while using v7 DATERANGE syntax."""
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
    """The last probed 1080p segment carries a mid-segment PTS regression."""
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
}


def apply_mutation(files: ScenarioFiles, name: str) -> ScenarioFiles:
    if name not in MUTATIONS:
        known = ", ".join(sorted(MUTATIONS))
        raise SystemExit(f"Unknown mutation {name!r}. Known mutations: {known}")
    return MUTATIONS[name][1](files)


def dump_fixture(fixture: dict[str, Any]) -> str:
    return json.dumps(fixture, indent=1) + "\n"
