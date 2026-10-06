"""A MediaLive metric over time for one pipeline, with its summary statistics."""

from datetime import datetime

from pydantic import BaseModel, computed_field


class MetricSeries(BaseModel):
    metric: str
    pipeline: str
    timestamps: list[datetime] = []
    values: list[float] = []

    @computed_field
    @property
    def latest(self) -> float | None:
        return self.values[-1] if self.values else None

    @computed_field
    @property
    def maximum(self) -> float | None:
        return max(self.values) if self.values else None

    @computed_field
    @property
    def average(self) -> float | None:
        return sum(self.values) / len(self.values) if self.values else None
