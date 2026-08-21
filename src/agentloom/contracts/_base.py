"""Boundary contract base types and Literal aliases."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

"""Versioned boundary contracts shared by AgentLoom components."""

Sha256Digest = str

RiskLevel = Literal["L0", "L1", "L2", "L3"]

EscalatedRiskLevel = Literal["L2", "L3"]

ApprovalStatus = Literal["PENDING", "APPROVED", "REJECTED", "EXPIRED"]

SkillLifecycleState = Literal[
    "DISCOVERED",
    "QUARANTINED",
    "SCANNED",
    "EVALUATING",
    "APPROVED",
    "PUBLISHED",
    "DEPRECATED",
    "BLOCKED",
    "REJECTED",
]

VerificationVerdict = Literal["PASSED", "FAILED", "UNSAFE", "UNCERTAIN"]

DetectionStageName = Literal["STATIC", "DYNAMIC", "VERIFICATION"]

TaskDetectionProducer = Literal["agentloom-implementer", "agentloom-verifier"]

ExperienceOutcome = Literal["SUCCEEDED", "FAILED", "UNCERTAIN"]

Severity = Literal["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]

TaskStatus = Literal[
    "RECEIVED",
    "PLANNED",
    "INVESTIGATING",
    "BLOCKED",
    "IMPLEMENTING",
    "AWAITING_APPROVAL",
    "VERIFYING",
    "ROLLING_BACK",
    "ROLLED_BACK",
    "LEARNING",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    "BLOCKED_PLATFORM",
]

CoordinationAgentName = Literal[
    "agentloom-manager",
    "agentloom-investigator",
    "agentloom-implementer",
    "agentloom-verifier",
]

CoordinationPhase = Literal[
    "MANAGER_DELEGATED",
    "IMPLEMENTER_ASSIGNED",
    "VERIFIER_ASSIGNED",
]

class ContractModel(BaseModel):
    """Strict base model for data crossing a process boundary."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )
