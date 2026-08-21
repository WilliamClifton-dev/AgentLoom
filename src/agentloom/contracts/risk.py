"""Boundary contract submodule: risk."""
from __future__ import annotations

from pydantic import (
    Field,
)

from agentloom.contracts._base import (
    ContractModel,
    RiskLevel,
    Severity,
    VerificationVerdict,
)


class Finding(ContractModel):
    rule_id: str = Field(min_length=1)
    severity: Severity
    message: str = Field(min_length=1)
    location: str | None = None
class RiskReport(ContractModel):
    task_id: str = Field(alias="taskId", min_length=1)
    risk_level: RiskLevel = Field(alias="riskLevel")
    verdict: VerificationVerdict
    findings: list[Finding]
    evidence_refs: list[str] = Field(alias="evidenceRefs", min_length=1)
