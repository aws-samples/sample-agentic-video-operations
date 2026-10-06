"""The machine-readable inspection report (spec §22). Schema kept CI-stable."""

from pydantic import BaseModel, Field

from hls_doctor.domain.correlate.finding_model import Finding
from hls_doctor.domain.evidence.evidence_store import EvidenceStore
from hls_doctor.domain.graph.presentation_node import PresentationNode


class ReportSummary(BaseModel):
    status: str
    presentation_type: str
    hls_version_declared: int | None = None
    features: list[str] = Field(default_factory=list)
    fatal: int = 0
    errors: int = 0
    warnings: int = 0
    info: int = 0


class PresentationInventory(BaseModel):
    variants: list[PresentationNode] = Field(default_factory=list)
    renditions: list[PresentationNode] = Field(default_factory=list)
    other_resources: list[PresentationNode] = Field(default_factory=list)


class InspectionReport(BaseModel):
    summary: ReportSummary
    presentation: PresentationInventory
    findings: list[Finding] = Field(default_factory=list)
    evidence: EvidenceStore = Field(default_factory=EvidenceStore)
