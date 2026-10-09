"""Classify the presentation and inventory its HLS features (spec §6B)."""

from typing import Literal

from pydantic import BaseModel, Field

from hls_doctor.domain.graph.build_presentation_graph import PresentationGraph
from hls_doctor.domain.playlist.media_playlist_model import MediaPlaylist

PresentationType = Literal["live", "event", "vod", "unknown"]


class PresentationProfile(BaseModel):
    presentation_type: PresentationType = "unknown"
    container: Literal["fmp4", "mpeg-ts", "mixed", "unknown"] = "unknown"
    declared_version: int | None = None
    encrypted: bool = False
    low_latency: bool = False
    features: list[str] = Field(default_factory=list)


def classify_presentation(graph: PresentationGraph) -> PresentationProfile:
    profile = PresentationProfile()
    features: set[str] = set()
    for parsed in graph.media_playlists():
        media = parsed.media
        if media is None:
            continue
        profile.presentation_type = classify_type(media.playlist_type, media.endlist)
        profile.declared_version = media.version or profile.declared_version
        collect_media_features(media, features)
    collect_multivariant_features(graph, features, profile)
    profile.container = classify_container(graph)
    profile.encrypted = "encryption" in features
    profile.low_latency = "ll-hls" in features
    profile.features = sorted(features)
    return profile


def classify_type(playlist_type: str | None, endlist: bool) -> PresentationType:
    if playlist_type == "VOD":
        return "vod"
    if playlist_type == "EVENT":
        return "event"
    return "vod" if endlist else "live"


def collect_media_features(media: MediaPlaylist, features: set[str]) -> None:
    if media.server_control or media.part_target or media.preload_hints:
        features.add("ll-hls")
    if media.dateranges:
        features.add("daterange")
    if any(d.range_class and "interstitial" in d.range_class.lower() for d in media.dateranges):
        features.add("interstitials")
    if any(segment.key and segment.key.method not in (None, "NONE") for segment in media.segments):
        features.add("encryption")
    if any(segment.cue_lines for segment in media.segments):
        features.add("scte35-cues")
    if any(segment.gap for segment in media.segments):
        features.add("gap")
    if any(segment.discontinuity for segment in media.segments):
        features.add("discontinuities")
    if any(segment.program_date_time for segment in media.segments):
        features.add("program-date-time")


def collect_multivariant_features(
    graph: PresentationGraph, features: set[str], profile: PresentationProfile
) -> None:
    entry = graph.multivariant
    if entry is None or entry.multivariant is None:
        return
    multivariant = entry.multivariant
    profile.declared_version = multivariant.version or profile.declared_version
    roles = {rendition.media_type.upper() for rendition in multivariant.renditions}
    if "AUDIO" in roles:
        features.add("alternate-audio")
    if "SUBTITLES" in roles:
        features.add("subtitles")
    if "CLOSED-CAPTIONS" in roles:
        features.add("closed-captions")
    if any(variant.iframe_only for variant in multivariant.variants):
        features.add("iframe-playlists")
    if multivariant.steering is not None:
        features.add("content-steering")
    if multivariant.defines:
        features.add("variable-substitution")
    if multivariant.session_keys:
        features.add("encryption")


def classify_container(graph: PresentationGraph) -> Literal["fmp4", "mpeg-ts", "mixed", "unknown"]:
    has_map = False
    has_ts = False
    for parsed in graph.media_playlists():
        if parsed.media is None:
            continue
        if any(segment.segment_map for segment in parsed.media.segments):
            has_map = True
        if any(segment.uri.split("?")[0].endswith(".ts") for segment in parsed.media.segments):
            has_ts = True
    if has_map and has_ts:
        return "mixed"
    if has_map:
        return "fmp4"
    if has_ts:
        return "mpeg-ts"
    return "unknown"
