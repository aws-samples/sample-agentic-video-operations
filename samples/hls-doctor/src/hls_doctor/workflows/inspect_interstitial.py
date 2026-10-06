"""Deep-dive one presentation's interstitials: asset lists, assets, compatibility (§12)."""

import json

from pydantic import BaseModel, Field

from hls_doctor.adapters.http.http_exchange import FetchUrl
from hls_doctor.domain.correlate.finding_model import Finding, create_finding, observe
from hls_doctor.domain.correlate.severity_model import Confidence, Severity
from hls_doctor.domain.evidence.evidence_store import EvidenceStore
from hls_doctor.domain.graph.build_presentation_graph import PresentationGraph
from hls_doctor.domain.playlist.resolve_uri import resolve_uri
from hls_doctor.domain.validate.validate_interstitials import interstitial_dateranges
from hls_doctor.workflows.build_probe_context import ProbeContext

COMPATIBLE_VIDEO_PREFIXES = ("avc1", "avc3", "hvc1", "hev1")


class InterstitialAsset(BaseModel):
    uri: str
    duration: float | None = None


class InterstitialEvent(BaseModel):
    event_id: str | None
    playlist_url: str
    asset_list_url: str | None = None
    asset_uri: str | None = None
    assets: list[InterstitialAsset] = Field(default_factory=list)


def inspect_interstitials(
    graph: PresentationGraph, context: ProbeContext, evidence: EvidenceStore
) -> list[Finding]:
    findings: list[Finding] = []
    for parsed in graph.media_playlists():
        if parsed.media is None:
            continue
        for daterange in interstitial_dateranges(parsed.media):
            event = InterstitialEvent(
                event_id=daterange.range_id,
                playlist_url=parsed.url,
                asset_uri=daterange.attributes.get("X-ASSET-URI"),
                asset_list_url=daterange.attributes.get("X-ASSET-LIST"),
            )
            inspect_event(event, context.fetch, evidence, findings)
    return findings


def inspect_event(
    event: InterstitialEvent,
    fetch: FetchUrl,
    evidence: EvidenceStore,
    findings: list[Finding],
) -> None:
    if event.asset_list_url:
        url = resolve_uri(event.asset_list_url, event.playlist_url)
        exchange = fetch(url)
        evidence_id = evidence.record_exchange(exchange)
        if not exchange.ok:
            findings.append(unreachable_asset_list(event, url, exchange.status, evidence_id))
            return
        read_asset_list(event, url, exchange.body_text or "", findings)
    for asset in event.assets or asset_from_uri(event):
        probe_asset(event, asset, fetch, evidence, findings)


def asset_from_uri(event: InterstitialEvent) -> list[InterstitialAsset]:
    if event.asset_uri is None:
        return []
    return [InterstitialAsset(uri=event.asset_uri)]


def unreachable_asset_list(
    event: InterstitialEvent, url: str, status: int | None, evidence_id: str
) -> Finding:
    return create_finding(
        "Interstitial asset list is unreachable",
        Severity.ERROR, Confidence.CONFIRMED, "interstitials", [url],
        [observe(f"X-ASSET-LIST for event {event.event_id!r} returned HTTP {status}",
                 evidence_id)],
        "Without the asset list the interstitial has no content to play.",
        "Clients skip or stall at the event, depending on X-RESTRICT.",
        next_probe="Request the asset list from the ad server directly.",
    )  # fmt: skip


def read_asset_list(event: InterstitialEvent, url: str, body: str, findings: list[Finding]) -> None:
    try:
        payload = json.loads(body)
        assets = payload["ASSETS"]
    except (json.JSONDecodeError, KeyError, TypeError):
        findings.append(
            create_finding(
                "Interstitial asset list is not valid asset-list JSON",
                Severity.ERROR,
                Confidence.CONFIRMED,
                "interstitials",
                [url],
                [
                    observe(
                        f"The response is not a JSON object with an ASSETS array"
                        f" (first bytes: {body[:60]!r})"
                    )
                ],
                "The asset list must follow the X-ASSET-LIST JSON format.",
                "Clients cannot load any interstitial content.",
            )  # fmt: skip
        )
        return
    for entry in assets:
        event.assets.append(
            InterstitialAsset(uri=str(entry.get("URI", "")), duration=entry.get("DURATION"))
        )


def probe_asset(
    event: InterstitialEvent,
    asset: InterstitialAsset,
    fetch: FetchUrl,
    evidence: EvidenceStore,
    findings: list[Finding],
) -> None:
    url = resolve_uri(asset.uri, event.playlist_url)
    exchange = fetch(url)
    evidence_id = evidence.record_exchange(exchange)
    if not exchange.ok:
        findings.append(
            create_finding(
                "Interstitial asset is unreachable",
                Severity.ERROR,
                Confidence.CONFIRMED,
                "interstitials",
                [url],
                [
                    observe(
                        f"Asset of event {event.event_id!r} returned HTTP {exchange.status}",
                        evidence_id,
                    )
                ],
                "The scheduled interstitial content cannot be fetched.",
                "Clients skip or stall at the event, depending on X-RESTRICT.",
            )  # fmt: skip
        )
        return
    check_asset_compatibility(event, url, exchange.body_text or "", findings)


def check_asset_compatibility(
    event: InterstitialEvent, url: str, body: str, findings: list[Finding]
) -> None:
    """An interstitial asset must itself be an HLS presentation a client can play."""
    if body.lstrip().startswith("#EXTM3U"):
        codecs_ok = any(prefix in body for prefix in COMPATIBLE_VIDEO_PREFIXES)
        if "CODECS" in body and not codecs_ok:
            findings.append(
                create_finding(
                    "Interstitial asset uses an incompatible video codec",
                    Severity.ERROR,
                    Confidence.HIGH,
                    "interstitials",
                    [url],
                    [
                        observe(
                            f"The asset playlist declares none of"
                            f" {', '.join(COMPATIBLE_VIDEO_PREFIXES)}"
                        )
                    ],
                    "Interstitial assets must be decodable by the primary content's clients.",
                    "Clients fail to switch into the interstitial and may stall at it.",
                    next_probe="Probe the asset's segments with ffprobe to confirm the codec.",
                )  # fmt: skip
            )
        return
    findings.append(
        create_finding(
            "Interstitial asset is not an HLS playlist",
            Severity.ERROR,
            Confidence.HIGH,
            "interstitials",
            [url],
            [
                observe(
                    f"Asset of event {event.event_id!r} does not start with #EXTM3U"
                    f" (first bytes: {body[:40]!r})"
                )
            ],
            "X-ASSET-URI and asset-list URIs must reference HLS assets.",
            "Clients cannot play the event content.",
        )  # fmt: skip
    )
