"""Severity describes impact; confidence describes evidence strength (spec §20)."""

from enum import StrEnum


class Severity(StrEnum):
    FATAL = "FATAL"
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


class Confidence(StrEnum):
    """Spec §21's `likely` maps to HIGH and `possible` to MEDIUM or LOW."""

    CONFIRMED = "confirmed"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


SEVERITY_ORDER = {
    Severity.FATAL: 0,
    Severity.ERROR: 1,
    Severity.WARNING: 2,
    Severity.INFO: 3,
}
