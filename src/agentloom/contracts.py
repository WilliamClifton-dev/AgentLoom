"""Versioned boundary contracts shared by AgentLoom components."""

from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Sha256Digest = str
RiskLevel = Literal["L0", "L1", "L2", "L3"]
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
Severity = Literal["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
TaskStatus = Literal[
    "RECEIVED",
    "PLANNED",
    "INVESTIGATING",
    "BLOCKED",
    "IMPLEMENTING",
    "AWAITING_APPROVAL",
    "VERIFYING",
    "LEARNING",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    "BLOCKED_PLATFORM",
]


class ContractModel(BaseModel):
    """Strict base model for data crossing a process boundary."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class AgentIdentity(ContractModel):
    name: str = Field(min_length=1)
    role: str = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)
    inputs: list[str] = Field(min_length=1)
    outputs: list[str] = Field(min_length=1)
    dependencies: list[str]
    decision_boundary: list[str] = Field(min_length=1)
    trace: list[str] = Field(min_length=1)


class SkillSource(ContractModel):
    repository: str = Field(min_length=1)
    path: str = Field(min_length=1)
    commit: str = Field(pattern=r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$")
    license: str = Field(min_length=1)
    content_hash: str = Field(
        alias="contentHash",
        pattern=r"^sha256:[a-f0-9]{64}$",
    )


class SkillEvaluation(ContractModel):
    upstream_evidence_refs: list[str] = Field(
        alias="upstreamEvidenceRefs",
        min_length=1,
    )
    agentloom_bench_evidence_refs: list[str] = Field(
        alias="agentloomBenchEvidenceRefs",
        min_length=1,
    )


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
    source: SkillSource | None = None
    compatible_agents: list[str] | None = Field(
        default=None,
        alias="compatibleAgents",
        min_length=1,
    )
    allowed_tools: list[str] | None = Field(
        default=None,
        alias="allowedTools",
        min_length=1,
    )
    allowed_paths: list[str] | None = Field(default=None, alias="allowedPaths")
    risk_level: RiskLevel | None = Field(default=None, alias="riskLevel")
    evaluation: SkillEvaluation | None = None
    lifecycle_state: SkillLifecycleState = Field(
        default="DISCOVERED",
        alias="lifecycleState",
    )

    @model_validator(mode="after")
    def published_skill_requires_governance_metadata(self) -> "SkillManifest":
        governed_states = {"APPROVED", "PUBLISHED", "DEPRECATED", "BLOCKED"}
        if self.lifecycle_state not in governed_states:
            return self
        required = {
            "source": self.source,
            "compatibleAgents": self.compatible_agents,
            "allowedTools": self.allowed_tools,
            "allowedPaths": self.allowed_paths,
            "riskLevel": self.risk_level,
            "evaluation": self.evaluation,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise ValueError(
                "approved or published Skill requires governance metadata: "
                + ", ".join(missing)
            )
        return self


class SkillCatalog(ContractModel):
    schema_version: Literal["agentloom.skill-catalog/v1alpha1"] = (
        "agentloom.skill-catalog/v1alpha1"
    )
    skills: list[SkillManifest] = Field(min_length=1)

    @model_validator(mode="after")
    def skill_versions_are_unique(self) -> "SkillCatalog":
        identities = [(skill.name, skill.version) for skill in self.skills]
        if len(identities) != len(set(identities)):
            raise ValueError("Skill catalog contains a duplicate name and version")
        return self


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
    grant_id: str = Field(alias="grantId", min_length=1)
    task_id: str = Field(alias="taskId", min_length=1)
    step_id: str = Field(alias="stepId", min_length=1)
    agent_name: str = Field(alias="agentName", min_length=1)
    skill_name: str = Field(alias="skillName", min_length=1)
    skill_version: str = Field(alias="skillVersion", min_length=1)
    skill_content_hash: str | None = Field(
        default=None,
        alias="skillContentHash",
        pattern=r"^sha256:[a-f0-9]{64}$",
    )
    tool_name: str = Field(alias="toolName", min_length=1)
    action: str = Field(min_length=1)
    parameter_digest: Sha256Digest = Field(
        alias="parameterDigest", pattern=r"^[a-f0-9]{64}$"
    )
    risk_level: RiskLevel = Field(alias="riskLevel")
    approval_ref: str | None = Field(default=None, alias="approvalRef")
    nonce: str = Field(min_length=8)
    issued_at: datetime = Field(alias="issuedAt")
    expires_at: datetime = Field(alias="expiresAt")

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


class Finding(ContractModel):
    rule_id: str = Field(min_length=1)
    severity: Severity
    message: str = Field(min_length=1)
    location: str | None = None


class DetectionResult(ContractModel):
    schema_version: Literal["agentloom.detection/v1alpha1"] = (
        "agentloom.detection/v1alpha1"
    )
    stage: DetectionStageName
    verdict: VerificationVerdict
    findings: list[Finding]
    evidence_refs: list[str]
    detector_versions: dict[str, str] = Field(min_length=1)


class DetectionReport(ContractModel):
    verdict: VerificationVerdict
    results: list[DetectionResult] = Field(min_length=1)
    evidence_refs: list[str]


class TaskCreate(ContractModel):
    title: str = Field(min_length=1, max_length=200)
    repository_uri: str = Field(alias="repositoryUri", min_length=1)
    issue: str = Field(min_length=1)
    acceptance_criteria: list[str] = Field(alias="acceptanceCriteria", min_length=1)
    allowed_paths: list[str] = Field(alias="allowedPaths", min_length=1)


class TaskRecord(TaskCreate):
    task_id: str = Field(alias="taskId", min_length=1)
    status: TaskStatus = "RECEIVED"
    plan_version: int = Field(default=0, alias="planVersion", ge=0)
    created_at: datetime = Field(alias="createdAt")


class TaskTransition(ContractModel):
    expected_plan_version: int = Field(alias="expectedPlanVersion", ge=0)
    status: TaskStatus
    reason: str = Field(min_length=1)


class TaskEventRecord(ContractModel):
    event_id: str = Field(alias="eventId", min_length=1)
    task_id: str = Field(alias="taskId", min_length=1)
    from_status: TaskStatus = Field(alias="fromStatus")
    to_status: TaskStatus = Field(alias="toStatus")
    plan_version: int = Field(alias="planVersion", ge=1)
    reason: str = Field(min_length=1)
    created_at: datetime = Field(alias="createdAt")


class GrantVerificationRequest(ContractModel):
    signed_grant: SignedSkillExecutionGrant = Field(alias="signedGrant")
    parameter_digest: Sha256Digest = Field(
        alias="parameterDigest", pattern=r"^[a-f0-9]{64}$"
    )


class Pagination(ContractModel):
    page: int = Field(ge=1)
    page_size: int = Field(alias="pageSize", ge=1, le=100)
    total_items: int = Field(alias="totalItems", ge=0)
    total_pages: int = Field(alias="totalPages", ge=0)


class TaskPage(ContractModel):
    data: list[TaskRecord]
    pagination: Pagination
