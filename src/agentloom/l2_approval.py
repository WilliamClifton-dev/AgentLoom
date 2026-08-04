"""Fail-closed verification of Human L2 decisions transported by Matrix."""

from __future__ import annotations

import hmac
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Literal
from uuid import uuid4

from pydantic import ConfigDict, Field, ValidationError, field_validator

from agentloom.contracts import (
    ApprovalCreate,
    ApprovalDecisionRequest,
    ApprovalRecord,
    ContractModel,
    TaskCreate,
)
from agentloom.storage import ApprovalVersionConflict, Database

_MAX_BODY_BYTES = 16_384


class L2ApprovalError(RuntimeError):
    """Raised when Matrix evidence cannot authorize an approval transition."""


class _StrictBoundaryModel(ContractModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=False,
        strict=True,
    )


class MatrixTextContent(_StrictBoundaryModel):
    msgtype: Literal["m.text"]
    body: str = Field(min_length=1)

    @field_validator("body")
    @classmethod
    def body_has_bounded_utf8_size(cls, value: str) -> str:
        if len(value.encode("utf-8")) > _MAX_BODY_BYTES:
            raise ValueError("Matrix message body exceeds the evidence size limit")
        return value


class MatrixTextEvent(_StrictBoundaryModel):
    room_id: str = Field(alias="roomId", pattern=r"^![^\s]+$")
    event_id: str = Field(alias="eventId", pattern=r"^\$[^\s]+$")
    sender: str = Field(pattern=r"^@[^\s:]+:[^\s]+$")
    origin_server_timestamp: int = Field(alias="originServerTimestamp", ge=1)
    event_type: Literal["m.room.message"] = Field(alias="type")
    content: MatrixTextContent


class L2ApprovalRequestMessage(_StrictBoundaryModel):
    schema_version: Literal["agentloom.l2-approval-request/v1alpha1"] = Field(
        default="agentloom.l2-approval-request/v1alpha1",
        alias="schemaVersion",
    )
    approval_id: str = Field(alias="approvalId", min_length=1, max_length=64)
    approval_version: int = Field(alias="approvalVersion", ge=0)
    task_id: str = Field(alias="taskId", min_length=1, max_length=64)
    grant_id: str = Field(alias="grantId", min_length=1, max_length=64)
    parameter_digest: str = Field(
        alias="parameterDigest", pattern=r"^[a-f0-9]{64}$"
    )
    risk_level: Literal["L2"] = Field(alias="riskLevel")
    route_id: str = Field(alias="routeId", min_length=1, max_length=200)
    rollback_plan_hash: str = Field(
        alias="rollbackPlanHash", pattern=r"^[a-f0-9]{64}$"
    )
    action_summary: str = Field(alias="actionSummary", min_length=1, max_length=500)
    expires_at: datetime = Field(alias="expiresAt")
    transport_origin: Literal["deterministic-host"] = Field(alias="transportOrigin")

    @field_validator("expires_at")
    @classmethod
    def expiry_is_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("approval expiry must be timezone-aware")
        return value


class L2ApprovalDecisionMessage(_StrictBoundaryModel):
    schema_version: Literal["agentloom.l2-approval-decision/v1alpha1"] = Field(
        alias="schemaVersion"
    )
    approval_id: str = Field(alias="approvalId", min_length=1, max_length=64)
    approval_version: int = Field(alias="approvalVersion", ge=0)
    task_id: str = Field(alias="taskId", min_length=1, max_length=64)
    grant_id: str = Field(alias="grantId", min_length=1, max_length=64)
    parameter_digest: str = Field(
        alias="parameterDigest", pattern=r"^[a-f0-9]{64}$"
    )
    risk_level: Literal["L2"] = Field(alias="riskLevel")
    route_id: str = Field(alias="routeId", min_length=1, max_length=200)
    rollback_plan_hash: str = Field(
        alias="rollbackPlanHash", pattern=r"^[a-f0-9]{64}$"
    )
    status: Literal["APPROVED", "REJECTED"]
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def reason_contains_non_whitespace(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("approval reason must contain non-whitespace text")
        return value


class L2ApprovalPreparation(_StrictBoundaryModel):
    schema_version: Literal["agentloom.l2-approval-preparation/v1alpha1"] = Field(
        default="agentloom.l2-approval-preparation/v1alpha1",
        alias="schemaVersion",
    )
    request: L2ApprovalRequestMessage


class L2ApprovalSubmission(_StrictBoundaryModel):
    schema_version: Literal["agentloom.l2-approval-submission/v1alpha1"] = Field(
        alias="schemaVersion"
    )
    request_event: MatrixTextEvent = Field(alias="requestEvent")
    decision_event: MatrixTextEvent = Field(alias="decisionEvent")


class ApprovalEvidenceEvent(_StrictBoundaryModel):
    event_id: str = Field(alias="eventId")
    sender: str
    origin_server_timestamp: int = Field(alias="originServerTimestamp")


class L2ApprovalEvidence(_StrictBoundaryModel):
    schema_version: Literal["agentloom.l2-approval-evidence/v1alpha1"] = Field(
        default="agentloom.l2-approval-evidence/v1alpha1",
        alias="schemaVersion",
    )
    approval_id: str = Field(alias="approvalId")
    approval_version: int = Field(alias="approvalVersion")
    task_id: str = Field(alias="taskId")
    grant_id: str = Field(alias="grantId")
    status: Literal["APPROVED", "REJECTED"]
    room_id: str = Field(alias="roomId")
    risk_level: Literal["L2"] = Field(alias="riskLevel")
    route_id: str = Field(alias="routeId")
    parameter_digest: str = Field(alias="parameterDigest")
    rollback_plan_hash: str = Field(alias="rollbackPlanHash")
    request_transport_origin: Literal["deterministic-host"] = Field(
        alias="requestTransportOrigin"
    )
    request_event: ApprovalEvidenceEvent = Field(alias="requestEvent")
    decision_event: ApprovalEvidenceEvent = Field(alias="decisionEvent")
    recorded_at: datetime = Field(alias="recordedAt")


class L2ApprovalVerifier:
    """Verify exact Manager request and Human decision events before persistence."""

    def __init__(
        self,
        database: Database,
        *,
        room_id: str,
        manager_user_id: str,
        human_user_id: str,
        clock: Callable[[], datetime] | None = None,
        max_event_age: timedelta = timedelta(minutes=15),
        max_future_skew: timedelta = timedelta(seconds=30),
    ) -> None:
        self._database = database
        self._room_id = room_id
        self._manager_user_id = manager_user_id
        self._human_user_id = human_user_id
        self._clock = clock or (lambda: datetime.now(UTC))
        self._max_event_age = max_event_age
        self._max_future_skew = max_future_skew

    def verify(
        self,
        request_event_value: object,
        decision_event_value: object,
    ) -> L2ApprovalEvidence:
        request_event = self._parse_event(request_event_value, "request")
        decision_event = self._parse_event(decision_event_value, "decision")
        self._verify_event_envelope(request_event, decision_event)
        request = self._parse_body(
            request_event.content.body,
            L2ApprovalRequestMessage,
            "request",
        )
        decision = self._parse_body(
            decision_event.content.body,
            L2ApprovalDecisionMessage,
            "decision",
        )
        assert isinstance(request, L2ApprovalRequestMessage)
        assert isinstance(decision, L2ApprovalDecisionMessage)

        if request.approval_id != decision.approval_id:
            raise L2ApprovalError("decision approval does not match the request")
        approval = self._database.get_approval(request.approval_id)
        if approval is None:
            raise L2ApprovalError("approval record does not exist")
        if approval.status != "PENDING":
            raise L2ApprovalError("approval is no longer pending")

        self._verify_request_binding(request, approval)
        self._verify_decision_binding(decision, request)
        now = self._aware_now()
        decision_time = _timestamp(decision_event)
        if now >= approval.expires_at or decision_time >= approval.expires_at:
            raise L2ApprovalError("approval decision is expired")

        try:
            updated = self._database.decide_approval(
                approval.approval_id,
                decision=self._decision_request(decision),
            )
        except ApprovalVersionConflict as exc:
            raise L2ApprovalError("approval was concurrently decided") from exc
        if updated is None or updated.status != decision.status:
            raise L2ApprovalError("approval decision could not be persisted")

        return L2ApprovalEvidence(
            approval_id=updated.approval_id,
            approval_version=updated.approval_version,
            task_id=updated.task_id,
            grant_id=updated.grant_id,
            status=decision.status,
            room_id=self._room_id,
            risk_level="L2",
            route_id=updated.route_id,
            parameter_digest=updated.parameter_digest,
            rollback_plan_hash=updated.rollback_plan_hash,
            request_transport_origin=request.transport_origin,
            request_event=_evidence_event(request_event),
            decision_event=_evidence_event(decision_event),
            recorded_at=now,
        )

    def verify_submission(
        self,
        submission: L2ApprovalSubmission,
    ) -> L2ApprovalEvidence:
        return self.verify(submission.request_event, submission.decision_event)

    @staticmethod
    def _parse_event(value: object, label: str) -> MatrixTextEvent:
        try:
            return MatrixTextEvent.model_validate(value)
        except ValidationError as exc:
            raise L2ApprovalError(f"invalid Matrix {label} event") from exc

    @staticmethod
    def _parse_body(
        body: str,
        model: type[L2ApprovalRequestMessage] | type[L2ApprovalDecisionMessage],
        label: str,
    ) -> L2ApprovalRequestMessage | L2ApprovalDecisionMessage:
        try:
            return model.model_validate_json(body)
        except ValidationError as exc:
            raise L2ApprovalError(f"invalid L2 approval {label} body") from exc

    def _verify_event_envelope(
        self,
        request: MatrixTextEvent,
        decision: MatrixTextEvent,
    ) -> None:
        if request.room_id != self._room_id or decision.room_id != self._room_id:
            raise L2ApprovalError("Matrix event is outside the configured Team Room")
        if request.sender != self._manager_user_id:
            raise L2ApprovalError("approval request sender is not the Manager")
        if decision.sender != self._human_user_id:
            raise L2ApprovalError("approval decision sender is not the Human")
        if request.event_id == decision.event_id:
            raise L2ApprovalError("request and decision must use distinct Matrix events")

        now = self._aware_now()
        request_time = _timestamp(request)
        decision_time = _timestamp(decision)
        if decision_time <= request_time:
            raise L2ApprovalError("approval decision must be newer than the request")
        for event_time in (request_time, decision_time):
            if event_time < now - self._max_event_age:
                raise L2ApprovalError("Matrix approval evidence is stale")
            if event_time > now + self._max_future_skew:
                raise L2ApprovalError("Matrix approval evidence is from the future")

    @staticmethod
    def _verify_request_binding(
        request: L2ApprovalRequestMessage,
        approval: ApprovalRecord,
    ) -> None:
        matches = (
            request.approval_version == approval.approval_version
            and request.task_id == approval.task_id
            and request.grant_id == approval.grant_id
            and hmac.compare_digest(request.parameter_digest, approval.parameter_digest)
            and request.risk_level == approval.risk_level
            and request.route_id == approval.route_id
            and hmac.compare_digest(
                request.rollback_plan_hash, approval.rollback_plan_hash
            )
            and request.action_summary == approval.action_summary
            and request.expires_at == approval.expires_at
        )
        if not matches:
            raise L2ApprovalError("approval request does not match the pending record")

    @staticmethod
    def _verify_decision_binding(
        decision: L2ApprovalDecisionMessage,
        request: L2ApprovalRequestMessage,
    ) -> None:
        matches = (
            decision.approval_id == request.approval_id
            and decision.approval_version == request.approval_version
            and decision.task_id == request.task_id
            and decision.grant_id == request.grant_id
            and hmac.compare_digest(decision.parameter_digest, request.parameter_digest)
            and decision.risk_level == request.risk_level
            and decision.route_id == request.route_id
            and hmac.compare_digest(
                decision.rollback_plan_hash, request.rollback_plan_hash
            )
        )
        if not matches:
            raise L2ApprovalError("approval decision does not match the request")

    def _decision_request(
        self,
        decision: L2ApprovalDecisionMessage,
    ) -> ApprovalDecisionRequest:
        return ApprovalDecisionRequest(
            expected_approval_version=decision.approval_version,
            status=decision.status,
            actor=self._human_user_id,
            reason=decision.reason,
        )

    def _aware_now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            raise L2ApprovalError("approval verifier clock must be timezone-aware")
        return now


def _timestamp(event: MatrixTextEvent) -> datetime:
    return datetime.fromtimestamp(event.origin_server_timestamp / 1000, tz=UTC)


def _evidence_event(event: MatrixTextEvent) -> ApprovalEvidenceEvent:
    return ApprovalEvidenceEvent(
        event_id=event.event_id,
        sender=event.sender,
        origin_server_timestamp=event.origin_server_timestamp,
    )


def prepare_l2_demo(
    database: Database,
    *,
    lifetime_minutes: int = 10,
) -> L2ApprovalPreparation:
    """Create a short-lived pending record and its exact Manager request body."""
    if not 1 <= lifetime_minutes <= 14:
        raise ValueError("L2 demo approval lifetime must be between 1 and 14 minutes")

    task = database.create_task(
        TaskCreate(
            title="Create a reviewed pull request",
            repository_uri="fixture://agentloom-l2-approval-demo",
            issue="A verified patch is ready for an external write.",
            acceptance_criteria=[
                "A Human approves or rejects the exact parameter-bound request."
            ],
            allowed_paths=["src/parser.py"],
        )
    )
    action_parameters = {
        "action": "github.pull-request.create",
        "repository": "fixture://agentloom-l2-approval-demo",
        "sourceBranch": "agentloom/verified-repair",
        "targetBranch": "main",
        "taskId": task.task_id,
    }
    rollback_plan = {
        "action": "github.pull-request.close",
        "deleteSourceBranch": False,
        "taskId": task.task_id,
    }
    now = datetime.now(UTC)
    request = ApprovalCreate(
        task_id=task.task_id,
        grant_id=f"grant-candidate-{uuid4().hex}",
        parameter_digest=_canonical_digest(action_parameters),
        risk_level="L2",
        route_id="github-pr-v1",
        rollback_plan_hash=_canonical_digest(rollback_plan),
        action_summary="Create a pull request from the independently verified patch.",
        requested_by="agentloom-implementer",
        expires_at=now + timedelta(minutes=lifetime_minutes),
    )
    approval = database.create_approval(request)
    return L2ApprovalPreparation(
        request=L2ApprovalRequestMessage(
            approval_id=approval.approval_id,
            approval_version=approval.approval_version,
            task_id=approval.task_id,
            grant_id=approval.grant_id,
            parameter_digest=approval.parameter_digest,
            risk_level="L2",
            route_id=approval.route_id,
            rollback_plan_hash=approval.rollback_plan_hash,
            action_summary=approval.action_summary,
            expires_at=approval.expires_at,
            transport_origin="deterministic-host",
        )
    )


def parse_l2_submission_json(value: str) -> L2ApprovalSubmission:
    """Parse untrusted collected evidence without exposing rejected values."""
    try:
        return L2ApprovalSubmission.model_validate_json(value)
    except ValidationError as exc:
        raise L2ApprovalError("invalid L2 approval submission") from exc


def _canonical_digest(value: Mapping[str, object]) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(payload).hexdigest()
