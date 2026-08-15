"""Versioned boundary contracts shared by AgentLoom components."""

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

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


class AgentIdentity(ContractModel):
    name: str = Field(min_length=1)
    role: str = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)
    inputs: list[str] = Field(min_length=1)
    outputs: list[str] = Field(min_length=1)
    dependencies: list[str]
    decision_boundary: list[str] = Field(min_length=1)
    trace: list[str] = Field(min_length=1)


class CoordinationEvent(ContractModel):
    phase: CoordinationPhase
    agent_name: CoordinationAgentName = Field(alias="agentName")
    matrix_user_id: str = Field(
        alias="matrixUserId",
        pattern=r"^@[^\s:]+:[^\s]+$",
    )
    mentioned_agent: CoordinationAgentName = Field(alias="mentionedAgent")
    mentioned_user_id: str = Field(
        alias="mentionedUserId",
        pattern=r"^@[^\s:]+:[^\s]+$",
    )
    room_id: str = Field(alias="roomId", pattern=r"^![^\s]+$")
    event_id: str = Field(alias="eventId", pattern=r"^\$[^\s]+$")
    origin_server_timestamp: int = Field(alias="originServerTimestamp", ge=1)

    @model_validator(mode="after")
    def phase_matches_sender_and_target(self) -> "CoordinationEvent":
        expected = {
            "MANAGER_DELEGATED": (
                "agentloom-manager",
                "agentloom-investigator",
            ),
            "IMPLEMENTER_ASSIGNED": (
                "agentloom-investigator",
                "agentloom-implementer",
            ),
            "VERIFIER_ASSIGNED": (
                "agentloom-investigator",
                "agentloom-verifier",
            ),
        }[self.phase]
        if (self.agent_name, self.mentioned_agent) != expected:
            raise ValueError("coordination phase does not match sender and target")
        expected_mention_prefix = f"@{self.mentioned_agent}:"
        if not self.mentioned_user_id.startswith(expected_mention_prefix):
            raise ValueError("mentioned user does not match mentioned Agent")
        if (
            self.agent_name != "agentloom-manager"
            and not self.matrix_user_id.startswith(f"@{self.agent_name}:")
        ):
            raise ValueError("sender user does not match coordination Agent")
        return self


class CoordinationTrace(ContractModel):
    schema_version: Literal["agentloom.coordination-trace/v1alpha1"] = Field(
        default="agentloom.coordination-trace/v1alpha1",
        alias="schemaVersion",
    )
    task_id: str = Field(
        alias="taskId",
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    )
    events: list[CoordinationEvent] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def events_form_one_strict_delegation_chain(self) -> "CoordinationTrace":
        expected_phases: tuple[CoordinationPhase, ...] = (
            "MANAGER_DELEGATED",
            "IMPLEMENTER_ASSIGNED",
            "VERIFIER_ASSIGNED",
        )
        if tuple(event.phase for event in self.events) != expected_phases:
            raise ValueError("coordination phases must follow the required order")
        if len({event.event_id for event in self.events}) != len(self.events):
            raise ValueError("coordination events must have distinct event IDs")
        timestamps = [event.origin_server_timestamp for event in self.events]
        if timestamps != sorted(timestamps) or len(set(timestamps)) != len(timestamps):
            raise ValueError("coordination events must be strictly ordered")
        return self


class SkillSource(ContractModel):
    repository: str = Field(min_length=1)
    path: str = Field(min_length=1)
    commit: str | None = Field(
        default=None,
        pattern=r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$",
    )
    workspace_snapshot: str | None = Field(
        default=None,
        alias="workspaceSnapshot",
        pattern=r"^sha256:[a-f0-9]{64}$",
    )
    license: str = Field(min_length=1)
    content_hash: str = Field(
        alias="contentHash",
        pattern=r"^sha256:[a-f0-9]{64}$",
    )

    @model_validator(mode="after")
    def revision_is_unambiguous_and_content_bound(self) -> "SkillSource":
        if (self.commit is None) == (self.workspace_snapshot is None):
            raise ValueError("Skill source requires exactly one revision binding")
        if (
            self.workspace_snapshot is not None
            and self.workspace_snapshot != self.content_hash
        ):
            raise ValueError("workspace snapshot must equal the Skill content hash")
        return self


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


class SkillResolutionRequest(ContractModel):
    """Request for one immutable Skill manifest from a provider."""

    name: str = Field(min_length=1)
    version: str | None = Field(default=None, min_length=1)


def tool_parameter_digest(parameters: Mapping[str, object]) -> str:
    """Return the canonical digest bound into a governed tool request."""

    encoded = json.dumps(
        dict(parameters),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ToolExecutionRequest(ContractModel):
    """Provider-neutral identity for one authorized tool execution."""

    task_id: str = Field(alias="taskId", min_length=1)
    step_id: str = Field(alias="stepId", min_length=1)
    agent_name: str = Field(alias="agentName", min_length=1)
    skill_name: str = Field(alias="skillName", min_length=1)
    skill_version: str = Field(alias="skillVersion", min_length=1)
    tool_name: str = Field(alias="toolName", min_length=1)
    action: str = Field(min_length=1)
    parameter_digest: Sha256Digest = Field(
        alias="parameterDigest", pattern=r"^[a-f0-9]{64}$"
    )
    parameters: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def parameters_match_digest(self) -> "ToolExecutionRequest":
        if self.parameter_digest != tool_parameter_digest(self.parameters):
            raise ValueError("parameters do not match parameterDigest")
        return self


class ToolExecutionResult(ContractModel):
    """Canonical result returned by every tool provider."""

    status: Literal["SUCCEEDED", "FAILED", "DENIED"]
    evidence_refs: list[str] = Field(alias="evidenceRefs", min_length=1)
    output_digest: Sha256Digest | None = Field(
        default=None,
        alias="outputDigest",
        pattern=r"^[a-f0-9]{64}$",
    )
    error_code: str | None = Field(default=None, alias="errorCode", min_length=1)

    @model_validator(mode="after")
    def result_fields_match_status(self) -> "ToolExecutionResult":
        if self.status == "SUCCEEDED" and self.error_code is not None:
            raise ValueError("successful tool execution cannot contain an error code")
        if self.status != "SUCCEEDED" and self.error_code is None:
            raise ValueError("failed or denied tool execution requires an error code")
        return self


class SandboxExecutionRequest(ContractModel):
    """Immutable snapshot and limits for one isolated process execution."""

    schema_version: Literal["agentloom.sandbox-execution/v1alpha1"] = Field(
        default="agentloom.sandbox-execution/v1alpha1",
        alias="schemaVersion",
    )
    execution_id: str = Field(
        alias="executionId",
        pattern=r"^sandbox-[a-f0-9]{16,64}$",
    )
    snapshot_uri: str = Field(alias="snapshotUri", min_length=1, max_length=4096)
    snapshot_digest: Sha256Digest = Field(
        alias="snapshotDigest",
        pattern=r"^[a-f0-9]{64}$",
    )
    command: list[str] = Field(min_length=1, max_length=64)
    working_directory: str = Field(
        alias="workingDirectory",
        min_length=1,
        max_length=1024,
    )
    timeout_seconds: int = Field(alias="timeoutSeconds", ge=1, le=120)
    output_limit_bytes: int = Field(
        alias="outputLimitBytes",
        ge=1024,
        le=1_048_576,
    )

    @field_validator("command")
    @classmethod
    def command_has_bounded_arguments(cls, value: list[str]) -> list[str]:
        if any(not argument or len(argument) > 4096 or "\x00" in argument for argument in value):
            raise ValueError("sandbox command contains an invalid argument")
        return value

    @field_validator("working_directory")
    @classmethod
    def working_directory_is_normalized(cls, value: str) -> str:
        if value == ".":
            return value
        if "\\" in value or "\x00" in value:
            raise ValueError("workingDirectory must use safe POSIX syntax")
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
            raise ValueError("workingDirectory must be a normalized relative path")
        return value


class SandboxExecutionResult(ContractModel):
    """Canonical output returned by every isolated execution backend."""

    schema_version: Literal["agentloom.sandbox-result/v1alpha1"] = Field(
        default="agentloom.sandbox-result/v1alpha1",
        alias="schemaVersion",
    )
    execution_id: str = Field(
        alias="executionId",
        pattern=r"^sandbox-[a-f0-9]{16,64}$",
    )
    provider_id: str = Field(alias="providerId", min_length=1, max_length=128)
    image_ref: str = Field(
        alias="imageRef",
        pattern=(
            r"^(?:sha256:[a-f0-9]{64}|"
            r"[a-z0-9][a-z0-9._/-]*@sha256:[a-f0-9]{64})$"
        ),
    )
    snapshot_digest: Sha256Digest = Field(
        alias="snapshotDigest",
        pattern=r"^[a-f0-9]{64}$",
    )
    exit_code: int = Field(alias="exitCode", ge=0, le=255)
    stdout: str = Field(max_length=1_048_576)
    stderr: str = Field(max_length=1_048_576)


TOOL_CALL_EVENT_SCHEMA_VERSION: Literal["agentloom.tool-call/v1alpha1"] = (
    "agentloom.tool-call/v1alpha1"
)
TOOL_CALL_EVENT_TYPE: Literal["TOOL_CALL"] = "TOOL_CALL"


def tool_call_payload_digest(payload: Mapping[str, object]) -> str:
    """Return the stable digest for one immutable tool call event payload."""

    encoded = json.dumps(
        dict(payload),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ToolCallEventRecord(ContractModel):
    """Replayable record of one provider-bound tool request and its result."""

    schema_version: Literal["agentloom.tool-call/v1alpha1"] = Field(
        default=TOOL_CALL_EVENT_SCHEMA_VERSION,
        alias="schemaVersion",
    )
    event_type: Literal["TOOL_CALL"] = Field(
        default=TOOL_CALL_EVENT_TYPE,
        alias="eventType",
    )
    event_id: str = Field(alias="eventId", min_length=1)
    task_id: str = Field(alias="taskId", min_length=1)
    step_id: str = Field(alias="stepId", min_length=1)
    actor: str = Field(min_length=1)
    provider_id: str = Field(alias="providerId", min_length=1)
    grant_id: str = Field(alias="grantId", min_length=1)
    tool_name: str = Field(alias="toolName", min_length=1)
    action: str = Field(min_length=1)
    parameter_digest: Sha256Digest = Field(
        alias="parameterDigest", pattern=r"^[a-f0-9]{64}$"
    )
    status: Literal["SUCCEEDED", "FAILED", "DENIED"]
    evidence_refs: list[str] = Field(alias="evidenceRefs", min_length=1)
    output_digest: Sha256Digest | None = Field(
        default=None,
        alias="outputDigest",
        pattern=r"^[a-f0-9]{64}$",
    )
    error_code: str | None = Field(default=None, alias="errorCode", min_length=1)
    causation_id: str | None = Field(default=None, alias="causationId", min_length=1)
    correlation_id: str = Field(alias="correlationId", min_length=1)
    payload_digest: Sha256Digest = Field(
        alias="payloadDigest", pattern=r"^[a-f0-9]{64}$"
    )
    created_at: datetime = Field(alias="createdAt")

    @classmethod
    def from_execution(
        cls,
        *,
        event_id: str,
        request: ToolExecutionRequest,
        result: ToolExecutionResult,
        provider_id: str,
        grant_id: str,
        actor: str,
        created_at: datetime,
    ) -> "ToolCallEventRecord":
        payload = cls._payload(
            task_id=request.task_id,
            step_id=request.step_id,
            actor=actor,
            provider_id=provider_id,
            grant_id=grant_id,
            tool_name=request.tool_name,
            action=request.action,
            parameter_digest=request.parameter_digest,
            status=result.status,
            evidence_refs=result.evidence_refs,
            output_digest=result.output_digest,
            error_code=result.error_code,
            causation_id=grant_id,
            correlation_id=request.task_id,
        )
        return cls(
            event_id=event_id,
            task_id=request.task_id,
            step_id=request.step_id,
            actor=actor,
            provider_id=provider_id,
            grant_id=grant_id,
            tool_name=request.tool_name,
            action=request.action,
            parameter_digest=request.parameter_digest,
            status=result.status,
            evidence_refs=result.evidence_refs,
            output_digest=result.output_digest,
            error_code=result.error_code,
            causation_id=grant_id,
            correlation_id=request.task_id,
            payload_digest=tool_call_payload_digest(payload),
            created_at=created_at,
        )

    @staticmethod
    def _payload(
        *,
        task_id: str,
        step_id: str,
        actor: str,
        provider_id: str,
        grant_id: str,
        tool_name: str,
        action: str,
        parameter_digest: str,
        status: str,
        evidence_refs: list[str],
        output_digest: str | None,
        error_code: str | None,
        causation_id: str | None,
        correlation_id: str,
    ) -> dict[str, object]:
        return {
            "schemaVersion": TOOL_CALL_EVENT_SCHEMA_VERSION,
            "eventType": TOOL_CALL_EVENT_TYPE,
            "taskId": task_id,
            "stepId": step_id,
            "actor": actor,
            "providerId": provider_id,
            "grantId": grant_id,
            "toolName": tool_name,
            "action": action,
            "parameterDigest": parameter_digest,
            "status": status,
            "evidenceRefs": evidence_refs,
            "outputDigest": output_digest,
            "errorCode": error_code,
            "causationId": causation_id,
            "correlationId": correlation_id,
        }

    def has_valid_payload_digest(self) -> bool:
        """Check that replayed request and result fields match the stored digest."""

        payload = self._payload(
            task_id=self.task_id,
            step_id=self.step_id,
            actor=self.actor,
            provider_id=self.provider_id,
            grant_id=self.grant_id,
            tool_name=self.tool_name,
            action=self.action,
            parameter_digest=self.parameter_digest,
            status=self.status,
            evidence_refs=self.evidence_refs,
            output_digest=self.output_digest,
            error_code=self.error_code,
            causation_id=self.causation_id,
            correlation_id=self.correlation_id,
        )
        return self.payload_digest == tool_call_payload_digest(payload)


class RootCauseReport(ContractModel):
    task_id: str = Field(alias="taskId", min_length=1)
    summary: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    evidence_refs: list[str] = Field(alias="evidenceRefs", min_length=1)
    repair_constraints: list[str] = Field(alias="repairConstraints")


class PatchArtifact(ContractModel):
    task_id: str = Field(alias="taskId", min_length=1)
    patch_uri: str = Field(alias="patchUri", min_length=1)
    sha256: Sha256Digest = Field(pattern=r"^[a-f0-9]{64}$")
    changed_paths: list[str] = Field(alias="changedPaths", min_length=1)
    evidence_refs: list[str] = Field(alias="evidenceRefs", min_length=1)


class VerificationRequest(ContractModel):
    """Provider-neutral input for independent patch verification."""

    task_id: str = Field(alias="taskId", min_length=1)
    patch: PatchArtifact
    evidence_refs: list[str] = Field(alias="evidenceRefs", min_length=1)
    allowed_paths: list[str] = Field(alias="allowedPaths", min_length=1)


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
    route_id: str | None = Field(default=None, alias="routeId", min_length=1)
    rollback_plan_hash: Sha256Digest | None = Field(
        default=None,
        alias="rollbackPlanHash",
        pattern=r"^[a-f0-9]{64}$",
    )
    parameter_digest: Sha256Digest = Field(
        alias="parameterDigest", pattern=r"^[a-f0-9]{64}$"
    )
    authorized_paths: list[str] = Field(alias="authorizedPaths", min_length=1)
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


SKILL_INVOCATION_SCHEMA_VERSION: Literal[
    "agentloom.skill-invocation/v1alpha1"
] = "agentloom.skill-invocation/v1alpha1"


def skill_invocation_payload_digest(payload: Mapping[str, object]) -> str:
    """Return the stable digest for one immutable Skill invocation closure."""

    encoded = json.dumps(
        dict(payload),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class SkillInvocationEvidenceRecord(ContractModel):
    """Bind one Skill version to its Grant, ToolCall, Agent, and Evidence."""

    schema_version: Literal["agentloom.skill-invocation/v1alpha1"] = Field(
        default=SKILL_INVOCATION_SCHEMA_VERSION,
        alias="schemaVersion",
    )
    invocation_id: str = Field(
        alias="invocationId",
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    )
    task_id: str = Field(alias="taskId", min_length=1)
    step_id: str = Field(alias="stepId", min_length=1)
    agent_name: str = Field(alias="agentName", min_length=1)
    skill_name: str = Field(alias="skillName", min_length=1)
    skill_version: str = Field(alias="skillVersion", min_length=1)
    skill_content_hash: str = Field(
        alias="skillContentHash",
        pattern=r"^sha256:[a-f0-9]{64}$",
    )
    grant_id: str = Field(alias="grantId", min_length=1)
    tool_call_event_id: str = Field(alias="toolCallEventId", min_length=1)
    tool_call_payload_digest: Sha256Digest = Field(
        alias="toolCallPayloadDigest",
        pattern=r"^[a-f0-9]{64}$",
    )
    input_digest: Sha256Digest = Field(
        alias="inputDigest",
        pattern=r"^[a-f0-9]{64}$",
    )
    output_digest: Sha256Digest = Field(
        alias="outputDigest",
        pattern=r"^[a-f0-9]{64}$",
    )
    evidence_ref: str = Field(alias="evidenceRef", min_length=1)
    evidence_sha256: Sha256Digest = Field(
        alias="evidenceSha256",
        pattern=r"^[a-f0-9]{64}$",
    )
    status: Literal["SUCCEEDED", "FAILED", "DENIED"]
    payload_digest: Sha256Digest = Field(
        alias="payloadDigest",
        pattern=r"^[a-f0-9]{64}$",
    )
    created_at: datetime = Field(alias="createdAt")

    @classmethod
    def from_execution(
        cls,
        *,
        invocation_id: str,
        request: ToolExecutionRequest,
        signed_grant: SignedSkillExecutionGrant,
        tool_call: ToolCallEventRecord,
    ) -> "SkillInvocationEvidenceRecord":
        grant = signed_grant.grant
        closure_matches = (
            grant.skill_content_hash is not None
            and grant.grant_id == tool_call.grant_id
            and grant.task_id == request.task_id == tool_call.task_id
            and grant.step_id == request.step_id == tool_call.step_id
            and grant.agent_name == request.agent_name == tool_call.actor
            and grant.skill_name == request.skill_name
            and grant.skill_version == request.skill_version
            and grant.tool_name == request.tool_name == tool_call.tool_name
            and grant.action == request.action == tool_call.action
            and grant.parameter_digest
            == request.parameter_digest
            == tool_call.parameter_digest
            and tool_call.output_digest is not None
            and len(tool_call.evidence_refs) == 1
            and tool_call.has_valid_payload_digest()
        )
        if not closure_matches:
            raise ValueError("Skill invocation execution closure does not match")
        assert grant.skill_content_hash is not None
        assert tool_call.output_digest is not None
        evidence_ref = tool_call.evidence_refs[0]
        payload = cls._payload(
            invocation_id=invocation_id,
            task_id=request.task_id,
            step_id=request.step_id,
            agent_name=request.agent_name,
            skill_name=request.skill_name,
            skill_version=request.skill_version,
            skill_content_hash=grant.skill_content_hash,
            grant_id=grant.grant_id,
            tool_call_event_id=tool_call.event_id,
            tool_call_payload_digest=tool_call.payload_digest,
            input_digest=request.parameter_digest,
            output_digest=tool_call.output_digest,
            evidence_ref=evidence_ref,
            evidence_sha256=tool_call.output_digest,
            status=tool_call.status,
        )
        return cls(
            **payload,
            payload_digest=skill_invocation_payload_digest(payload),
            created_at=tool_call.created_at,
        )

    @staticmethod
    def _payload(
        *,
        invocation_id: str,
        task_id: str,
        step_id: str,
        agent_name: str,
        skill_name: str,
        skill_version: str,
        skill_content_hash: str,
        grant_id: str,
        tool_call_event_id: str,
        tool_call_payload_digest: str,
        input_digest: str,
        output_digest: str,
        evidence_ref: str,
        evidence_sha256: str,
        status: str,
    ) -> dict[str, object]:
        return {
            "schemaVersion": SKILL_INVOCATION_SCHEMA_VERSION,
            "invocationId": invocation_id,
            "taskId": task_id,
            "stepId": step_id,
            "agentName": agent_name,
            "skillName": skill_name,
            "skillVersion": skill_version,
            "skillContentHash": skill_content_hash,
            "grantId": grant_id,
            "toolCallEventId": tool_call_event_id,
            "toolCallPayloadDigest": tool_call_payload_digest,
            "inputDigest": input_digest,
            "outputDigest": output_digest,
            "evidenceRef": evidence_ref,
            "evidenceSha256": evidence_sha256,
            "status": status,
        }

    def has_valid_payload_digest(self) -> bool:
        payload = self._payload(
            invocation_id=self.invocation_id,
            task_id=self.task_id,
            step_id=self.step_id,
            agent_name=self.agent_name,
            skill_name=self.skill_name,
            skill_version=self.skill_version,
            skill_content_hash=self.skill_content_hash,
            grant_id=self.grant_id,
            tool_call_event_id=self.tool_call_event_id,
            tool_call_payload_digest=self.tool_call_payload_digest,
            input_digest=self.input_digest,
            output_digest=self.output_digest,
            evidence_ref=self.evidence_ref,
            evidence_sha256=self.evidence_sha256,
            status=self.status,
        )
        return self.payload_digest == skill_invocation_payload_digest(payload)


class GrantIssuanceRequest(ContractModel):
    """Caller-controlled fields for one server-derived execution Grant."""

    task_id: str = Field(alias="taskId", min_length=1)
    step_id: str = Field(alias="stepId", min_length=1)
    skill_name: str = Field(alias="skillName", min_length=1)
    skill_version: str = Field(alias="skillVersion", min_length=1)
    tool_name: str = Field(alias="toolName", min_length=1)
    action: str = Field(min_length=1)
    parameter_digest: Sha256Digest = Field(
        alias="parameterDigest",
        pattern=r"^[a-f0-9]{64}$",
    )
    requested_paths: list[str] = Field(alias="requestedPaths", min_length=1)


class ToolExecutionEnvelope(ContractModel):
    """Policy-bound tool request passed from the MCP boundary to a provider."""

    signed_grant: SignedSkillExecutionGrant = Field(alias="signedGrant")
    tool_request: ToolExecutionRequest = Field(alias="toolRequest")

    @model_validator(mode="after")
    def request_matches_grant(self) -> "ToolExecutionEnvelope":
        grant = self.signed_grant.grant
        request = self.tool_request
        matching_fields = (
            (request.task_id, grant.task_id),
            (request.step_id, grant.step_id),
            (request.agent_name, grant.agent_name),
            (request.skill_name, grant.skill_name),
            (request.skill_version, grant.skill_version),
            (request.tool_name, grant.tool_name),
            (request.action, grant.action),
            (request.parameter_digest, grant.parameter_digest),
        )
        if any(requested != authorized for requested, authorized in matching_fields):
            raise ValueError("toolRequest does not match signed grant")
        return self


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


class RepairArtifactBundle(ContractModel):
    root_cause: RootCauseReport = Field(alias="rootCause")
    patch: PatchArtifact
    verification: VerificationResult
    risk: RiskReport

    @model_validator(mode="after")
    def role_outputs_refer_to_one_verified_patch(self) -> "RepairArtifactBundle":
        task_ids = {
            self.root_cause.task_id,
            self.patch.task_id,
            self.verification.task_id,
            self.risk.task_id,
        }
        if len(task_ids) != 1:
            raise ValueError("repair artifacts must use the same taskId")
        if self.patch.sha256 != self.verification.patch_hash:
            raise ValueError("verification patch hash must match PatchArtifact")
        return self


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


class TaskDetectionRecord(ContractModel):
    """Bind one generic DetectionResult to a task, subject, and Agent owner."""

    schema_version: Literal["agentloom.task-detection/v1alpha1"] = Field(
        default="agentloom.task-detection/v1alpha1",
        alias="schemaVersion",
    )
    detection_id: str = Field(alias="detectionId", min_length=1)
    task_id: str = Field(alias="taskId", min_length=1)
    step_id: str = Field(alias="stepId", min_length=1)
    producer_agent: TaskDetectionProducer = Field(alias="producerAgent")
    subject_digest: Sha256Digest = Field(
        alias="subjectDigest",
        pattern=r"^[a-f0-9]{64}$",
    )
    result: DetectionResult
    created_at: datetime = Field(alias="createdAt")

    @model_validator(mode="after")
    def stage_has_independent_owner_and_evidence(self) -> "TaskDetectionRecord":
        expected_producer: TaskDetectionProducer = (
            "agentloom-verifier"
            if self.result.stage == "VERIFICATION"
            else "agentloom-implementer"
        )
        if self.producer_agent != expected_producer:
            raise ValueError(
                f"{self.result.stage} must be produced by {expected_producer}"
            )
        if not self.result.evidence_refs:
            raise ValueError("task detection requires at least one Evidence reference")
        if self.created_at.tzinfo is None:
            raise ValueError("task detection timestamp must be timezone-aware")
        return self


class ExperienceRecord(ContractModel):
    """Immutable terminal learning record whose conclusion is evidence-backed."""

    schema_version: Literal["agentloom.experience/v1alpha1"] = Field(
        default="agentloom.experience/v1alpha1",
        alias="schemaVersion",
    )
    experience_id: str = Field(alias="experienceId", min_length=1)
    task_id: str = Field(alias="taskId", min_length=1)
    outcome: ExperienceOutcome
    verdict: VerificationVerdict
    skill_versions: dict[str, str] = Field(alias="skillVersions")
    failure_mode: str | None = Field(default=None, alias="failureMode", min_length=1)
    lessons: list[str] = Field(min_length=1)
    evidence_refs: list[str] = Field(alias="evidenceRefs", min_length=1)
    created_at: datetime = Field(alias="createdAt")

    @model_validator(mode="after")
    def outcome_matches_verdict_and_failure_mode(self) -> "ExperienceRecord":
        valid = (
            self.outcome == "SUCCEEDED"
            and self.verdict == "PASSED"
            and self.failure_mode is None
        ) or (
            self.outcome == "FAILED"
            and self.verdict in {"FAILED", "UNSAFE"}
            and self.failure_mode is not None
        ) or (
            self.outcome == "UNCERTAIN"
            and self.verdict == "UNCERTAIN"
            and self.failure_mode is not None
        )
        if not valid:
            raise ValueError("experience outcome is inconsistent with terminal verdict")
        if self.created_at.tzinfo is None:
            raise ValueError("experience timestamp must be timezone-aware")
        return self


class TaskEvidenceBundle(ContractModel):
    """Closed evidence set for one task's three-layer terminal conclusion."""

    schema_version: Literal["agentloom.task-evidence-bundle/v1alpha1"] = Field(
        default="agentloom.task-evidence-bundle/v1alpha1",
        alias="schemaVersion",
    )
    task_id: str = Field(alias="taskId", min_length=1)
    detections: list[TaskDetectionRecord] = Field(min_length=3, max_length=3)
    evidence: list[EvidenceRecord] = Field(min_length=3)
    experience: ExperienceRecord

    @model_validator(mode="after")
    def evidence_is_closed_and_role_separated(self) -> "TaskEvidenceBundle":
        if [record.result.stage for record in self.detections] != [
            "STATIC",
            "DYNAMIC",
            "VERIFICATION",
        ]:
            raise ValueError(
                "task evidence must contain ordered STATIC, DYNAMIC, and VERIFICATION"
            )
        task_ids = {
            self.task_id,
            self.experience.task_id,
            *(record.task_id for record in self.detections),
            *(record.task_id for record in self.evidence),
        }
        if len(task_ids) != 1:
            raise ValueError("task evidence records must use the same taskId")

        detection_ids = [record.detection_id for record in self.detections]
        evidence_ids = [record.evidence_id for record in self.evidence]
        if len(detection_ids) != len(set(detection_ids)):
            raise ValueError("task evidence contains duplicate detection IDs")
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("task evidence contains duplicate Evidence IDs")
        evidence_by_id = {record.evidence_id: record for record in self.evidence}
        stage_evidence_sets = [
            set(detection.result.evidence_refs) for detection in self.detections
        ]
        for index, evidence_set in enumerate(stage_evidence_sets):
            if any(evidence_set & prior for prior in stage_evidence_sets[:index]):
                raise ValueError("each detection stage requires distinct Evidence")
        stage_evidence_ids = set().union(*stage_evidence_sets)
        unresolved = stage_evidence_ids - evidence_by_id.keys()
        if unresolved:
            raise ValueError("task detection contains unresolved Evidence references")
        if stage_evidence_ids != evidence_by_id.keys():
            raise ValueError("every task Evidence must belong to one detection stage")
        for detection in self.detections:
            for evidence_id in detection.result.evidence_refs:
                if evidence_by_id[evidence_id].producer != detection.producer_agent:
                    raise ValueError("task detection Evidence producer does not match Agent")

        unresolved_experience = set(self.experience.evidence_refs) - evidence_by_id.keys()
        if unresolved_experience:
            raise ValueError("ExperienceRecord contains unresolved Evidence references")
        if not stage_evidence_ids.issubset(self.experience.evidence_refs):
            raise ValueError("ExperienceRecord must reference every stage Evidence")
        if any(
            record.result.verdict != "PASSED" for record in self.detections[:2]
        ):
            raise ValueError("STATIC and DYNAMIC must pass before VERIFICATION")
        if self.experience.verdict != self.detections[2].result.verdict:
            raise ValueError("experience verdict must match VERIFICATION verdict")
        return self


class ApprovalCreate(ContractModel):
    schema_version: Literal["agentloom.approval/v1alpha1"] = Field(
        default="agentloom.approval/v1alpha1",
        alias="schemaVersion",
    )
    task_id: str = Field(alias="taskId", min_length=1)
    grant_id: str = Field(alias="grantId", min_length=1)
    parameter_digest: Sha256Digest = Field(
        alias="parameterDigest", pattern=r"^[a-f0-9]{64}$"
    )
    risk_level: EscalatedRiskLevel = Field(alias="riskLevel")
    route_id: str = Field(alias="routeId", min_length=1, max_length=200)
    rollback_plan_hash: Sha256Digest = Field(
        alias="rollbackPlanHash", pattern=r"^[a-f0-9]{64}$"
    )
    action_summary: str = Field(alias="actionSummary", min_length=1, max_length=500)
    requested_by: str = Field(alias="requestedBy", min_length=1, max_length=200)
    expires_at: datetime = Field(alias="expiresAt")

    @field_validator("expires_at")
    @classmethod
    def expiry_is_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("approval expiry must be timezone-aware")
        return value


class ApprovalRecord(ApprovalCreate):
    approval_id: str = Field(alias="approvalId", min_length=1)
    status: ApprovalStatus = "PENDING"
    approval_version: int = Field(default=0, alias="approvalVersion", ge=0)
    created_at: datetime = Field(alias="createdAt")
    decided_by: str | None = Field(default=None, alias="decidedBy")
    decision_reason: str | None = Field(default=None, alias="decisionReason")
    decided_at: datetime | None = Field(default=None, alias="decidedAt")

    @model_validator(mode="after")
    def approval_state_is_bound_and_short_lived(self) -> "ApprovalRecord":
        if self.created_at.tzinfo is None:
            raise ValueError("approval creation time must be timezone-aware")
        if self.expires_at <= self.created_at:
            raise ValueError("approval expiry must follow creation time")
        if self.expires_at - self.created_at > timedelta(minutes=15):
            raise ValueError("approval lifetime cannot exceed 15 minutes")
        decision_present = (
            self.decided_by is not None
            or self.decision_reason is not None
            or self.decided_at is not None
        )
        if self.status == "PENDING":
            if decision_present or self.approval_version != 0:
                raise ValueError("pending approval cannot contain a decision")
            return self
        if self.status in {"APPROVED", "REJECTED"}:
            if (
                not self.decided_by
                or not self.decision_reason
                or self.decided_at is None
                or self.decided_at.tzinfo is None
                or self.approval_version < 1
            ):
                raise ValueError(
                    "approved or rejected approval requires actor, reason, and timestamp"
                )
            return self
        if decision_present:
            raise ValueError("expired approval cannot contain a decision")
        return self


class ApprovalDecisionRequest(ContractModel):
    expected_approval_version: int = Field(alias="expectedApprovalVersion", ge=0)
    status: Literal["APPROVED", "REJECTED"]
    actor: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=500)


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


WorkflowVerificationOutcome = Literal["PASSED", "FAILED", "UNSAFE", "UNCERTAIN"]
WorkflowCompletionOutcome = Literal["PASSED", "FAILED", "CANCELLED"]

TASK_EVENT_SCHEMA_VERSION: Literal["agentloom.task-event/v1alpha1"] = (
    "agentloom.task-event/v1alpha1"
)
TASK_EVENT_TYPE: Literal["TASK_STATUS_TRANSITION"] = "TASK_STATUS_TRANSITION"


def task_event_payload_digest(payload: Mapping[str, object]) -> str:
    """Return the stable digest for the non-volatile TaskEvent payload."""

    encoded = json.dumps(
        dict(payload),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class TaskEventRecord(ContractModel):
    schema_version: Literal["agentloom.task-event/v1alpha1"] = Field(
        default=TASK_EVENT_SCHEMA_VERSION,
        alias="schemaVersion",
    )
    event_type: Literal["TASK_STATUS_TRANSITION"] = Field(
        default=TASK_EVENT_TYPE,
        alias="eventType",
    )
    event_id: str = Field(alias="eventId", min_length=1)
    task_id: str = Field(alias="taskId", min_length=1)
    from_status: TaskStatus = Field(alias="fromStatus")
    to_status: TaskStatus = Field(alias="toStatus")
    plan_version: int = Field(alias="planVersion", ge=1)
    reason: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    causation_id: str | None = Field(default=None, alias="causationId")
    correlation_id: str = Field(alias="correlationId", min_length=1)
    payload_digest: Sha256Digest = Field(
        alias="payloadDigest",
        pattern=r"^[a-f0-9]{64}$",
    )
    created_at: datetime = Field(alias="createdAt")

    @classmethod
    def from_transition(
        cls,
        *,
        event_id: str,
        task_id: str,
        from_status: TaskStatus,
        to_status: TaskStatus,
        plan_version: int,
        reason: str,
        actor: str,
        causation_id: str | None,
        created_at: datetime,
    ) -> "TaskEventRecord":
        payload: dict[str, object] = {
            "schemaVersion": TASK_EVENT_SCHEMA_VERSION,
            "eventType": TASK_EVENT_TYPE,
            "taskId": task_id,
            "fromStatus": from_status,
            "toStatus": to_status,
            "planVersion": plan_version,
            "reason": reason,
            "actor": actor,
            "causationId": causation_id,
            "correlationId": task_id,
        }
        return cls(
            schema_version=TASK_EVENT_SCHEMA_VERSION,
            event_type=TASK_EVENT_TYPE,
            event_id=event_id,
            task_id=task_id,
            from_status=from_status,
            to_status=to_status,
            plan_version=plan_version,
            reason=reason,
            actor=actor,
            causation_id=causation_id,
            correlation_id=task_id,
            payload_digest=task_event_payload_digest(payload),
            created_at=created_at,
        )

    def has_valid_payload_digest(self) -> bool:
        """Check that replayed event fields match the stored payload digest."""

        payload: dict[str, object] = {
            "schemaVersion": self.schema_version,
            "eventType": self.event_type,
            "taskId": self.task_id,
            "fromStatus": self.from_status,
            "toStatus": self.to_status,
            "planVersion": self.plan_version,
            "reason": self.reason,
            "actor": self.actor,
            "causationId": self.causation_id,
            "correlationId": self.correlation_id,
        }
        return self.payload_digest == task_event_payload_digest(payload)


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
