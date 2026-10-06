"""Deterministic fault injections for HLS Doctor fixture scenarios.

Each mutation is a pure function over a recorded http.exchanges fixture dict.
`scripts/mutate_hls_fixtures.py` applies one and writes the derived scenario;
the acceptance corpus in `fixtures/` is regenerated this way, so every broken
stream is provenance-traceable to a base recording plus one named mutation.
"""

import copy
import json
from collections.abc import Callable
from typing import Any

Fixture = dict[str, Any]
Mutation = Callable[[Fixture], Fixture]

NOT_FOUND_BODY = "<html><body><h1>404 Not Found</h1></body></html>"
EXPIRED_TOKEN_BODY = (
    '<?xml version="1.0"?><Error><Code>AccessDenied</Code>'  # noqa: S105 - error body, no secret
    "<Message>Request has expired</Message></Error>"
)


def _playlists(fixture: Fixture) -> dict[str, Any]:
    return {
        url: entry
        for url, entry in fixture["exchanges"].items()
        if url.endswith(".m3u8") and "body" in entry
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


def _edit_body(entry: dict[str, Any], old: str, new: str, *, required: bool = True) -> None:
    if required and old not in entry["body"]:
        raise ValueError(f"mutation target {old!r} not present in the base body")
    entry["body"] = entry["body"].replace(old, new)


def missing_variant(fixture: Fixture) -> Fixture:
    """The lowest ABR variant's media playlist returns 404."""
    mutated = copy.deepcopy(fixture)
    url = next(url for url in _playlists(mutated) if "/v480/" in url)
    _not_found(mutated["exchanges"][url])
    return mutated


def wrong_version(fixture: Fixture) -> Fixture:
    """The 1080p playlist declares EXT-X-VERSION:3 while using v7 DATERANGE syntax."""
    mutated = copy.deepcopy(fixture)
    url = next(url for url in _playlists(mutated) if "/v1080/" in url)
    _edit_body(mutated["exchanges"][url], "#EXT-X-VERSION:7", "#EXT-X-VERSION:3")
    return mutated


def targetduration_exceeded(fixture: Fixture) -> Fixture:
    """One 1080p segment advertises 8.5 s against TARGETDURATION 6."""
    mutated = copy.deepcopy(fixture)
    url = next(url for url in _playlists(mutated) if "/v1080/" in url)
    entry = mutated["exchanges"][url]
    _edit_body(entry, "#EXTINF:6.00000,\nseg3.m4s", "#EXTINF:8.50000,\nseg3.m4s")
    return mutated


def broken_map(fixture: Fixture) -> Fixture:
    """The 1080p initialization section returns 404."""
    mutated = copy.deepcopy(fixture)
    url = next(url for url in mutated["exchanges"] if "/v1080/init.mp4" in url)
    _not_found(mutated["exchanges"][url])
    return mutated


def expired_key(fixture: Fixture) -> Fixture:
    """The content key URL returns 403 with an expiry-shaped error body."""
    mutated = copy.deepcopy(fixture)
    url = next(url for url in mutated["exchanges"] if url.endswith("content.key"))
    entry = mutated["exchanges"][url]
    entry.clear()
    entry.update(
        {
            "status": 403,
            "headers": {"content-type": "application/xml", "server": "demo-cdn"},
            "body": EXPIRED_TOKEN_BODY,
        }
    )
    return mutated


def subtitle_playlist_404(fixture: Fixture) -> Fixture:
    """The English subtitle rendition playlist returns 404."""
    mutated = copy.deepcopy(fixture)
    url = next(url for url in mutated["exchanges"] if "/subs/en/prog.m3u8" in url)
    _not_found(mutated["exchanges"][url])
    return mutated


MUTATIONS: dict[str, Mutation] = {
    "hls_missing_variant": missing_variant,
    "hls_wrong_version": wrong_version,
    "hls_targetduration_exceeded": targetduration_exceeded,
    "hls_broken_map": broken_map,
    "hls_expired_key": expired_key,
    "hls_subtitle_playlist_404": subtitle_playlist_404,
}


def apply_mutation(fixture: Fixture, name: str) -> Fixture:
    if name not in MUTATIONS:
        known = ", ".join(sorted(MUTATIONS))
        raise SystemExit(f"Unknown mutation {name!r}. Known mutations: {known}")
    return MUTATIONS[name](fixture)


def dump_fixture(fixture: Fixture) -> str:
    return json.dumps(fixture, indent=1) + "\n"
