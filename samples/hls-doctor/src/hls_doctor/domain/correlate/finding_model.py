"""The diagnostic record every check produces (spec §21)."""

from pydantic import BaseModel, Field

from hls_doctor.domain.correlate.severity_model import Confidence, Severity


class Observation(BaseModel):
    """One fact with its evidence reference; never an interpretation."""

    statement: str
    evidence_id: str | None = None


def observe(statement: str, evidence_id: str | None = None) -> "Observation":
    return Observation(statement=statement, evidence_id=evidence_id)


def create_finding(
    title: str,
    severity: Severity,
    confidence: Confidence,
    category: str,
    resources: list[str],
    observations: list[Observation],
    interpretation: str,
    playback_impact: str,
    *,
    likely_causes: list[str] | None = None,
    next_probe: str | None = None,
    remediation: str | None = None,
    standards_reference: str | None = None,
) -> "Finding":
    """A Finding without an id; correlate_findings assigns ids when ranking."""
    return Finding(
        finding_id="",
        title=title,
        severity=severity,
        confidence=confidence,
        category=category,
        affected_resources=resources,
        observations=observations,
        interpretation=interpretation,
        playback_impact=playback_impact,
        likely_causes=likely_causes or [],
        next_probe=next_probe,
        remediation=remediation,
        standards_reference=standards_reference,
    )


class Finding(BaseModel):
    finding_id: str
    title: str
    severity: Severity
    confidence: Confidence
    category: str
    affected_resources: list[str] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)
    interpretation: str
    playback_impact: str
    likely_causes: list[str] = Field(default_factory=list)
    next_probe: str | None = None
    remediation: str | None = None
    standards_reference: str | None = None
