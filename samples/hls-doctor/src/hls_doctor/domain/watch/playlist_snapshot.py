"""One observed reload of a live Media Playlist (spec §9)."""

from pydantic import BaseModel, Field

from hls_doctor.domain.playlist.media_playlist_model import MediaPlaylist


class PlaylistSnapshot(BaseModel):
    url: str
    at_ms: int
    evidence_id: str
    media_sequence: int
    discontinuity_sequence: int
    segment_count: int
    newest_msn: int | None = None
    newest_uri: str | None = None
    newest_program_date_time: str | None = None
    endlist: bool
    etag: str | None = None
    age_header: str | None = None
    advertised_msns: list[int] = Field(default_factory=list)


def build_snapshot(
    url: str, at_ms: int, evidence_id: str, media: MediaPlaylist, etag: str | None, age: str | None
) -> PlaylistSnapshot:
    newest = media.segments[-1] if media.segments else None
    return PlaylistSnapshot(
        url=url,
        at_ms=at_ms,
        evidence_id=evidence_id,
        media_sequence=media.media_sequence,
        discontinuity_sequence=media.discontinuity_sequence,
        segment_count=len(media.segments),
        newest_msn=newest.media_sequence_number if newest else None,
        newest_uri=newest.uri if newest else None,
        newest_program_date_time=newest.program_date_time if newest else None,
        endlist=media.endlist,
        etag=etag,
        age_header=age,
        advertised_msns=[segment.media_sequence_number for segment in media.segments],
    )
