from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from agentloom.contracts import (
    SignedSkillExecutionGrant,
    SkillExecutionGrant,
    SkillInvocationEvidenceRecord,
    ToolCallEventRecord,
    ToolExecutionRequest,
    ToolExecutionResult,
    skill_invocation_payload_digest,
    tool_parameter_digest,
)
from agentloom.skill_invocations import ImmutableSkillInvocationWriter


def _closure() -> tuple[
    ToolExecutionRequest,
    SignedSkillExecutionGrant,
    ToolCallEventRecord,
]:
    parameters: dict[str, object] = {"patch": "canonical-diff"}
    request = ToolExecutionRequest(
        task_id="task-scope-01",
        step_id="scope-01",
        agent_name="agentloom-verifier",
        skill_name="patch-scope-validator",
        skill_version="1.0.1",
        tool_name="patch-scope-validator",
        action="patch.validate:scope",
        parameter_digest=tool_parameter_digest(parameters),
        parameters=parameters,
    )
    now = datetime(2026, 8, 15, tzinfo=UTC)
    grant = SkillExecutionGrant(
        grant_id="grant-scope-01",
        task_id=request.task_id,
        step_id=request.step_id,
        agent_name=request.agent_name,
        skill_name=request.skill_name,
        skill_version=request.skill_version,
        skill_content_hash=f"sha256:{'a' * 64}",
        tool_name=request.tool_name,
        action=request.action,
        parameter_digest=request.parameter_digest,
        authorized_paths=["src/severity.py"],
        risk_level="L0",
        nonce="nonce-scope-01",
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    signed = SignedSkillExecutionGrant(grant=grant, signature="b" * 64)
    result = ToolExecutionResult(
        status="SUCCEEDED",
        evidence_refs=["ev-scope-01"],
        output_digest="c" * 64,
    )
    event = ToolCallEventRecord.from_execution(
        event_id="tool-event-scope-01",
        request=request,
        result=result,
        provider_id="patch-scope-validator/v1.0.1",
        grant_id=grant.grant_id,
        actor=request.agent_name,
        created_at=now,
    )
    return request, signed, event


def test_skill_invocation_record_binds_complete_execution_closure() -> None:
    request, signed, event = _closure()

    record = SkillInvocationEvidenceRecord.from_execution(
        invocation_id="skill-invocation-scope-01",
        request=request,
        signed_grant=signed,
        tool_call=event,
    )

    assert record.schema_version == "agentloom.skill-invocation/v1alpha1"
    assert record.skill_name == "patch-scope-validator"
    assert record.skill_version == "1.0.1"
    assert record.skill_content_hash == f"sha256:{'a' * 64}"
    assert record.agent_name == "agentloom-verifier"
    assert record.tool_call_event_id == "tool-event-scope-01"
    assert record.tool_call_payload_digest == event.payload_digest
    assert record.input_digest == request.parameter_digest
    assert record.output_digest == "c" * 64
    assert record.evidence_ref == "ev-scope-01"
    assert record.evidence_sha256 == "c" * 64
    assert record.has_valid_payload_digest()
    tampered = record.model_copy(update={"agent_name": "agentloom-implementer"})
    assert not tampered.has_valid_payload_digest()


def test_skill_invocation_record_rejects_mismatched_grant_or_tool_call() -> None:
    request, signed, event = _closure()
    mismatched_event = event.model_copy(update={"step_id": "other-step"})

    with pytest.raises(ValueError, match="execution closure"):
        SkillInvocationEvidenceRecord.from_execution(
            invocation_id="skill-invocation-scope-01",
            request=request,
            signed_grant=signed,
            tool_call=mismatched_event,
        )


def test_immutable_skill_invocation_writer_refuses_overwrite(tmp_path: Path) -> None:
    request, signed, event = _closure()
    record = SkillInvocationEvidenceRecord.from_execution(
        invocation_id="skill-invocation-scope-01",
        request=request,
        signed_grant=signed,
        tool_call=event,
    )
    writer = ImmutableSkillInvocationWriter(tmp_path)

    output = writer(record)

    assert output == record
    evidence_path = tmp_path / "skill-invocation-scope-01.json"
    assert SkillInvocationEvidenceRecord.model_validate_json(
        evidence_path.read_text(encoding="utf-8")
    ) == record
    with pytest.raises(FileExistsError):
        writer(record)


def test_immutable_skill_invocation_writer_rejects_path_escape(tmp_path: Path) -> None:
    request, signed, event = _closure()
    record = SkillInvocationEvidenceRecord.from_execution(
        invocation_id="skill-invocation-scope-01",
        request=request,
        signed_grant=signed,
        tool_call=event,
    )
    payload = record._payload(
        invocation_id="../escaped",
        task_id=record.task_id,
        step_id=record.step_id,
        agent_name=record.agent_name,
        skill_name=record.skill_name,
        skill_version=record.skill_version,
        skill_content_hash=record.skill_content_hash,
        grant_id=record.grant_id,
        tool_call_event_id=record.tool_call_event_id,
        tool_call_payload_digest=record.tool_call_payload_digest,
        input_digest=record.input_digest,
        output_digest=record.output_digest,
        evidence_ref=record.evidence_ref,
        evidence_sha256=record.evidence_sha256,
        status=record.status,
    )
    escaped_digest = skill_invocation_payload_digest(payload)
    with pytest.raises(ValidationError):
        SkillInvocationEvidenceRecord(
            **payload,
            payload_digest=escaped_digest,
            created_at=record.created_at,
        )
    escaped = record.model_copy(
        update={
            "invocation_id": "../escaped",
            "payload_digest": escaped_digest,
        }
    )

    with pytest.raises(ValueError, match="invocation ID"):
        ImmutableSkillInvocationWriter(tmp_path)(escaped)
