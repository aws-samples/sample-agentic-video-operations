"""A MediaLive metric over time for one pipeline, with its summaries.

`dimensions` holds the dimensions beyond ChannelId and Pipeline that the series was read
with, such as OutputGroupName, AudioDescriptionName or Region (region-wide metrics).


`statistic` is the CloudWatch statistic of each 5-minute value. `total` exists only for Sum
series, where adding periods is meaningful; averages are never added up.
"""

from datetime import datetime

from pydantic import BaseModel, computed_field


class MetricSeries(BaseModel):
    metric: str
    pipeline: str
    statistic: str = "Average"
    dimensions: dict[str, str] = {}
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

    @computed_field
    @property
    def total(self) -> float | None:
        return sum(self.values) if self.statistic == "Sum" and self.values else None

    @computed_field
    @property
    def emitted(self) -> bool:
        """False when CloudWatch returned no datapoints: unknown, never healthy."""
        return bool(self.values)
