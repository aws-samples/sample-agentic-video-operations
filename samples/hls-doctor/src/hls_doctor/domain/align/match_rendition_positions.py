"""Position matching across renditions: MSN and wall-clock views (spec §11)."""

from datetime import datetime

from pydantic import BaseModel, Field

from hls_doctor.domain.playlist.media_playlist_model import MediaPlaylist


class RenditionPosition(BaseModel):
    url: str
    role: str
    target_duration: int | None = None
    newest_msn: int | None = None
    pdt_by_msn: dict[int, datetime] = Field(default_factory=dict)
    daterange_ids: list[str] = Field(default_factory=list)
    discontinuity_msns: list[int] = Field(default_factory=list)


def read_position(url: str, role: str, media: MediaPlaylist) -> RenditionPosition:
    position = RenditionPosition(
        url=url,
        role=role,
        target_duration=media.target_duration,
        newest_msn=media.segments[-1].media_sequence_number if media.segments else None,
        daterange_ids=sorted(d.range_id for d in media.dateranges if d.range_id),
        discontinuity_msns=[
            segment.media_sequence_number for segment in media.segments if segment.discontinuity
        ],
    )
    for segment in media.segments:
        if segment.program_date_time:
            parsed = parse_program_date_time(segment.program_date_time)
            if parsed is not None:
                position.pdt_by_msn[segment.media_sequence_number] = parsed
    return position


def parse_program_date_time(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
