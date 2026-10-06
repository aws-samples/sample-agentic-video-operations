"""The window every pack's visual-quality sampler accepts, in one place."""

MIN_FRAMES = 2  # two frames are the least that can show change
MAX_FRAMES = 20  # the Converse request's image limit
MIN_WINDOW_SECONDS = 1
MAX_WINDOW_SECONDS = 120  # the tool blocks for the whole window


def window_is_allowed(frames: int, window_seconds: int) -> bool:
    return (
        MIN_FRAMES <= frames <= MAX_FRAMES
        and MIN_WINDOW_SECONDS <= window_seconds <= MAX_WINDOW_SECONDS
    )


WINDOW_REFUSAL = (
    f"frames must be {MIN_FRAMES}-{MAX_FRAMES} and window_seconds "
    f"{MIN_WINDOW_SECONDS}-{MAX_WINDOW_SECONDS}."
)
