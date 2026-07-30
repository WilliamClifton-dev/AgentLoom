"""Versioned boundary contracts shared by AgentLoom components."""

from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Sha256Digest = str
RiskLevel = Literal["L0", "L1", "L2", "L3"]
VerificationVerdict = Literal["PASSED", "FAILED", "UNSAFE", "UNCERTAIN"]


class ContractModel(BaseModel):
    """Strict base model for data crossing a process boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class AgentIdentity(ContractModel):
    name: str = Field(min_length=1)
    role: str = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)
    inputs: list[str] = Field(min_length=1)
    outputs: list[str] = Field(min_length=1)
    dependencies: list[str]
    decision_boundary: list[str] = Field(min_length=1)
    trace: list[str] = Field(min_length=1)


class SkillManifest(ContractModel):
    schema_version: Literal["agentloom.skill/v1alpha1"] = "agentloom.skill/v1alpha1"
    name: str = Field(min_length=1)
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
    skill_type: str = Field(min_length=1)
    scenarios: list[str] = Field(min_length=1)
    input_schema: str = Field(min_length=1)
    output_schema: str = Field(min_length=1)
    invocation_conditions: list[str] = Field(min_length=1)
    dependencies: list[str]
    failure_modes: list[str] = Field(min_length=1)
    permissions: list[str]
    security_boundary: str = Field(min_length=1)
    reuse_value: str = Field(min_length=1)


class EvidenceRecord(ContractModel):
    schema_version: Literal["agentloom.evidence/v1alpha1"] = (
        "agentloom.evidence/v1alpha1"
    )
    evidence_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    step_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    producer: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    sha256: Sha256Digest = Field(pattern=r"^[a-f0-9]{64}$")
    summary: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class VerificationChecks(ContractModel):
    original_failure_reproduced: bool
    target_tests_passed: bool
    regression_tests_passed: bool
    static_checks_passed: bool
    unauthorized_changes: bool

    def mandatory_checks_pass(self) -> bool:
        return (
            self.original_failure_reproduced
            and self.target_tests_passed
            and self.regression_tests_passed
            and self.static_checks_passed
            and not self.unauthorized_changes
        )


class VerificationResult(ContractModel):
    schema_version: Literal["agentloom.verification/v1alpha1"] = (
        "agentloom.verification/v1alpha1"
    )
    task_id: str = Field(min_length=1)
    patch_hash: Sha256Digest = Field(pattern=r"^[a-f0-9]{64}$")
    verdict: VerificationVerdict
    checks: VerificationChecks
    evidence_refs: list[str] = Field(min_length=1)
    reason: str = Field(min_length=1)
    verifier_agent: str = Field(min_length=1)

    @model_validator(mode="after")
    def passed_verdict_requires_mandatory_checks(self) -> "VerificationResult":
        if self.verdict == "PASSED" and not self.checks.mandatory_checks_pass():
            raise ValueError("PASSED verdict requires every mandatory check to pass")
        return self


class SkillExecutionGrant(ContractModel):
    schema_version: Literal["agentloom.grant/v1alpha1"] = "agentloom.grant/v1alpha1"
    grant_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    step_id: str = Field(min_length=1)
    agent_name: str = Field(min_length=1)
    skill_name: str = Field(min_length=1)
    skill_version: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    action: str = Field(min_length=1)
    parameter_digest: Sha256Digest = Field(pattern=r"^[a-f0-9]{64}$")
    risk_level: RiskLevel
    approval_ref: str | None = None
    nonce: str = Field(min_length=8)
    issued_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def validate_time_window(self) -> "SkillExecutionGrant":
        if self.issued_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("grant timestamps must be timezone-aware")
        if self.expires_at <= self.issued_at:
            raise ValueError("grant expiry must follow issue time")
        if self.expires_at - self.issued_at > timedelta(minutes=15):
            raise ValueError("grant lifetime cannot exceed 15 minutes")
        return self


class SignedSkillExecutionGrant(ContractModel):
    grant: SkillExecutionGrant
    signature: str = Field(pattern=r"^[a-f0-9]{64}$")
