"""Which fixture scenario a sample replays (write_safe_tools.md §4, build_a_sample.md §5)."""


def resolve_demo_scenario(value: str | None, sample_default: str) -> str:
    """An empty or unset DEMO_SCENARIO means the sample's own default scenario.

    The root .env.example ships `DEMO_SCENARIO=` so that every sample keeps its default;
    pydantic-settings reads that as "", which must never mean "no scenario".
    """
    return value.strip() if value and value.strip() else sample_default
