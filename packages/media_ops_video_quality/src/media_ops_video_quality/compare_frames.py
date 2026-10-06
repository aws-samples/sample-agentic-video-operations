"""How much the picture changed between two consecutive sampled frames."""

from PIL import ImageChops, ImageStat
from pydantic import BaseModel

from media_ops_video_quality.measure_frame import analysis_copy, decode_gray


class FrameChange(BaseModel):
    mean_abs_difference: float  # 8-bit luma levels, at the 320-px analysis width


def compare_frames(previous: bytes, current: bytes) -> FrameChange:
    a, b = analysis_copy(decode_gray(previous)), analysis_copy(decode_gray(current))
    if a.size != b.size:
        b = b.resize(a.size)
    difference = ImageChops.difference(a, b)
    return FrameChange(mean_abs_difference=ImageStat.Stat(difference).mean[0])
