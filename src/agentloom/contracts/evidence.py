"""Boundary contract submodule: evidence."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover  (typing only; cycle-free at runtime)
    from agentloom.contracts.repair import ExperienceRecord, TaskDetectionRecord


import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Literal

from pydantic import (
    Field,
    model_validator,
)

from agentloom.contracts._base import (
    ContractModel,
    Sha256Digest,
    VerificationVerdict,
)
from agentloom.contracts.grant import (
    SignedSkillExecutionGrant,
)
from agentloom.contracts.tool import (
    ToolCallEventRecord,
    ToolExecutionRequest,
)


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
    def passed_verdict_requires_mandatory_checks(self) -> VerificationResult:
        if self.verdict == "PASSED" and not self.checks.mandatory_checks_pass():
            raise ValueError("PASSED verdict requires every mandatory check to pass")
        return self
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
    ) -> SkillInvocationEvidenceRecord:
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
class TaskEvidenceBundle(ContractModel):
    """Closed evidence set for one task's three-layer terminal conclusion."""

    schema_version: Literal["agentloom.task-evidence-bundle/v1alpha1"] = Field(
        default="agentloom.task-evidence-bundle/v1alpha1",
        alias="schemaVersion",
    )
    task_id: str = Field(alias="taskId", min_length=1)
    detections: list[TaskDetectionRecord] = Field(min_length=3, max_length=3)  # noqa: F821
    evidence: list[EvidenceRecord] = Field(min_length=3)
    experience: ExperienceRecord  # noqa: F821

    @model_validator(mode="after")
    def evidence_is_closed_and_role_separated(self) -> TaskEvidenceBundle:
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
