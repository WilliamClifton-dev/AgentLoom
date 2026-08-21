"""Boundary contract submodule: repair."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import (
    Field,
    model_validator,
)

from agentloom.contracts._base import (
    ContractModel,
    DetectionStageName,
    ExperienceOutcome,
    Sha256Digest,
    TaskDetectionProducer,
    VerificationVerdict,
)
from agentloom.contracts.evidence import (
    PatchArtifact,
    RootCauseReport,
    VerificationResult,
)
from agentloom.contracts.risk import Finding, RiskReport  # noqa: F401  (forward refs)


class RepairArtifactBundle(ContractModel):
    root_cause: RootCauseReport = Field(alias="rootCause")
    patch: PatchArtifact
    verification: VerificationResult
    risk: RiskReport

    @model_validator(mode="after")
    def role_outputs_refer_to_one_verified_patch(self) -> RepairArtifactBundle:
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
    def stage_has_independent_owner_and_evidence(self) -> TaskDetectionRecord:
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
    def outcome_matches_verdict_and_failure_mode(self) -> ExperienceRecord:
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
