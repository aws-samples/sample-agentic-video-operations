"""Deterministic, no-reference measurements of one JPEG frame (Pillow only, no model call).

- sharpness: variance of a Laplacian over a 320-px-wide grayscale copy. Soft or blurred
  pictures have little high-frequency energy, so a low value means blur.
- blockiness_estimate: how much larger the luma step is across 8-px block boundaries than
  inside blocks, in 8-bit levels, at the thumbnail's own resolution (about 0 when no grid
  shows). An estimate, not a standard metric: the thumbnail is itself a JPEG, so its own
  encoder's blocks contribute as well as the stream's. A ratio was rejected because blur
  shrinks the interior steps and inflates it.
- luma: mean, standard deviation and the share of pixels clipped at video black (<= 16) or
  white (>= 235). Black is dark and flat; a slate or flat field is flat at any level.
- palette_concentration: the share of pixels in the three most populated 8-level luma bins.
  A card, slate or caption screen is a few flat colours, so most of it falls in a few bins;
  a natural picture spreads across many. It is what tells a moving text card from programme
  when every other measurement reads both as clean.
"""

import io
from typing import cast

from PIL import Image, ImageChops, ImageFilter, ImageStat, UnidentifiedImageError
from pydantic import BaseModel

from media_ops_video_quality.decode_thumbnail import invalid_thumbnail

ANALYSIS_WIDTH = 320
LAPLACIAN = ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=1, offset=128)
BLOCK = 8


class FrameMetrics(BaseModel):
    width: int
    height: int
    sharpness: float
    blockiness_estimate: float
    luma_mean: float
    luma_stddev: float
    clipped_share: float
    palette_concentration: float


def decode_gray(jpeg: bytes) -> Image.Image:
    """Bytes the image library can't read are a typed failure, not a library error."""
    try:
        with Image.open(io.BytesIO(jpeg)) as image:
            return image.convert("L")
    except (UnidentifiedImageError, OSError, ValueError):
        raise invalid_thumbnail() from None


def analysis_copy(gray: Image.Image) -> Image.Image:
    """A fixed-width copy, so sharpness compares across thumbnail sizes."""
    if gray.width == ANALYSIS_WIDTH:
        return gray
    height = max(1, round(gray.height * ANALYSIS_WIDTH / gray.width))
    return gray.resize((ANALYSIS_WIDTH, height), Image.Resampling.BILINEAR)


def measure_frame(jpeg: bytes) -> FrameMetrics:
    gray = decode_gray(jpeg)
    small = analysis_copy(gray)
    stat = ImageStat.Stat(small)
    histogram = small.histogram()
    clipped = sum(histogram[:17]) + sum(histogram[235:])
    pixels = small.width * small.height
    bins = sorted(sum(histogram[start : start + 8]) for start in range(0, 256, 8))
    return FrameMetrics(
        width=gray.width,
        height=gray.height,
        sharpness=ImageStat.Stat(small.filter(LAPLACIAN)).var[0],
        blockiness_estimate=estimate_blockiness(gray),
        luma_mean=stat.mean[0],
        luma_stddev=stat.stddev[0],
        clipped_share=clipped / pixels,
        palette_concentration=sum(bins[-3:]) / pixels,
    )


def estimate_blockiness(gray: Image.Image) -> float:
    """Mean boundary step minus mean interior step on the 8-px grid, in luma levels, >= 0."""
    steps = column_steps(gray) + column_steps(gray.transpose(Image.Transpose.TRANSPOSE))
    boundary = [step for index, step in steps if index % BLOCK == BLOCK - 1]
    interior = [step for index, step in steps if index % BLOCK != BLOCK - 1]
    if not boundary or not interior:
        return 0.0
    return max(0.0, sum(boundary) / len(boundary) - sum(interior) / len(interior))


def column_steps(gray: Image.Image) -> list[tuple[int, float]]:
    """(x, mean |I(x+1) - I(x)| over all rows) for each column x, computed with Pillow ops."""
    width, height = gray.size
    if width < 2 * BLOCK:
        return []
    left = gray.crop((0, 0, width - 1, height))
    right = gray.crop((1, 0, width, height))
    difference = ImageChops.difference(left, right).convert("F")  # float: keep small steps
    steps = difference.resize((width - 1, 1), Image.Resampling.BOX)
    values = cast(list[float], list(steps.get_flattened_data()))  # mode F: one float per pixel
    return list(enumerate(values))
