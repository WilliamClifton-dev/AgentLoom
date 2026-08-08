from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from agentloom.contracts import (
    AgentIdentity,
    ApprovalDecisionRequest,
    ApprovalRecord,
    CoordinationEvent,
    CoordinationTrace,
    EvidenceRecord,
    Finding,
    PatchArtifact,
    RepairArtifactBundle,
    RiskReport,
    RootCauseReport,
    SkillEvaluation,
    SkillExecutionGrant,
    SkillManifest,
    SkillSource,
    VerificationChecks,
    VerificationResult,
)


def make_coordination_trace() -> CoordinationTrace:
    return CoordinationTrace(
        task_id="task-01",
        events=[
            CoordinationEvent(
                phase="MANAGER_DELEGATED",
                agent_name="agentloom-manager",
                matrix_user_id="@admin:example.test",
                mentioned_agent="agentloom-investigator",
                mentioned_user_id="@agentloom-investigator:example.test",
                room_id="!manager:example.test",
                event_id="$manager-delegated",
                origin_server_timestamp=1_700_000_000_001,
            ),
            CoordinationEvent(
                phase="IMPLEMENTER_ASSIGNED",
                agent_name="agentloom-investigator",
                matrix_user_id="@agentloom-investigator:example.test",
                mentioned_agent="agentloom-implementer",
                mentioned_user_id="@agentloom-implementer:example.test",
                room_id="!repair:example.test",
                event_id="$implementer-assigned",
                origin_server_timestamp=1_700_000_000_003,
            ),
            CoordinationEvent(
                phase="VERIFIER_ASSIGNED",
                agent_name="agentloom-investigator",
                matrix_user_id="@agentloom-investigator:example.test",
                mentioned_agent="agentloom-verifier",
                mentioned_user_id="@agentloom-verifier:example.test",
                room_id="!repair:example.test",
                event_id="$verifier-assigned",
                origin_server_timestamp=1_700_000_000_005,
            ),
        ],
    )


def test_coordination_trace_binds_existing_agents_and_mentions() -> None:
    trace = make_coordination_trace()

    assert [event.phase for event in trace.events] == [
        "MANAGER_DELEGATED",
        "IMPLEMENTER_ASSIGNED",
        "VERIFIER_ASSIGNED",
    ]
    assert trace.events[1].mentioned_agent == "agentloom-implementer"


def test_coordination_trace_rejects_wrong_target_and_event_order() -> None:
    valid = make_coordination_trace()

    with pytest.raises(ValidationError, match="phase does not match"):
        CoordinationTrace(
            task_id="task-01",
            events=[
                valid.events[0],
                valid.events[1].model_copy(
                    update={
                        "mentioned_agent": "agentloom-verifier",
                        "mentioned_user_id": "@agentloom-verifier:example.test",
                    }
                ),
                valid.events[2],
            ],
        )

    with pytest.raises(ValidationError, match="strictly ordered"):
        CoordinationTrace(
            task_id="task-01",
            events=[
                valid.events[0],
                valid.events[1].model_copy(
                    update={"origin_server_timestamp": 1_700_000_000_006}
                ),
                valid.events[2],
            ],
        )


def test_approval_record_binds_l2_request_to_parameters_and_rollback_plan() -> None:
    created_at = datetime.now(UTC)
    record = ApprovalRecord(
        approval_id="approval-01",
        task_id="task-01",
        grant_id="grant-01",
        parameter_digest="a" * 64,
        risk_level="L2",
        route_id="github-pr-v1",
        rollback_plan_hash="b" * 64,
        action_summary="Create a pull request from the verified patch.",
        requested_by="agentloom-implementer",
        expires_at=created_at + timedelta(minutes=10),
        created_at=created_at,
    )

    assert record.status == "PENDING"
    assert record.approval_version == 0
    assert record.parameter_digest == "a" * 64


def test_approval_contract_rejects_non_escalated_risk_and_unbound_decisions() -> None:
    created_at = datetime.now(UTC)
    values = {
        "approval_id": "approval-01",
        "task_id": "task-01",
        "grant_id": "grant-01",
        "parameter_digest": "a" * 64,
        "risk_level": "L1",
        "route_id": "github-pr-v1",
        "rollback_plan_hash": "b" * 64,
        "action_summary": "Create a pull request from the verified patch.",
        "requested_by": "agentloom-implementer",
        "expires_at": created_at + timedelta(minutes=10),
        "created_at": created_at,
    }
    with pytest.raises(ValidationError):
        ApprovalRecord.model_validate(values)

    with pytest.raises(ValidationError, match="requires actor, reason, and timestamp"):
        ApprovalRecord.model_validate({**values, "risk_level": "L2", "status": "APPROVED"})


def test_approval_decision_requires_a_current_version_and_a_reason() -> None:
    with pytest.raises(ValidationError):
        ApprovalDecisionRequest(
            expected_approval_version=-1,
            status="APPROVED",
            actor="agentloom-developer",
            reason="Approved after reviewing the rollback plan.",
        )
    with pytest.raises(ValidationError):
        ApprovalDecisionRequest(
            expected_approval_version=0,
            status="APPROVED",
            actor="agentloom-developer",
            reason="",
        )


def test_agent_identity_requires_explicit_decision_boundary() -> None:
    with pytest.raises(ValidationError):
        AgentIdentity.model_validate(
            {
                "name": "agentloom-investigator",
                "role": "root cause investigator",
                "capabilities": ["repo.read"],
                "inputs": ["Issue"],
                "outputs": ["RootCauseReport"],
                "dependencies": ["debugging-skill"],
                "trace": ["Matrix event"],
            }
        )


def test_skill_manifest_captures_appendix_b_fields() -> None:
    manifest = SkillManifest(
        name="debugging-and-error-recovery",
        version="1.0.0",
        skill_type="external-skill",
        scenarios=["bug-triage"],
        input_schema="schemas/debugging-input.json",
        output_schema="schemas/root-cause-report.json",
        invocation_conditions=["issue-and-repository-present"],
        dependencies=["repository-search"],
        failure_modes=["INSUFFICIENT_EVIDENCE", "TIMEOUT"],
        permissions=["repo.read"],
        security_boundary="L0 read-only, network denied",
        reuse_value="Reusable for incident and defect investigation",
    )

    assert manifest.name == "debugging-and-error-recovery"
    assert manifest.permissions == ["repo.read"]


def test_published_skill_requires_complete_governance_metadata() -> None:
    with pytest.raises(ValidationError, match="approved or published Skill requires"):
        SkillManifest(
            name="debugging-and-error-recovery",
            version="1.0.0",
            skill_type="external-skill",
            scenarios=["bug-triage"],
            input_schema="schemas/debugging-input.json",
            output_schema="schemas/root-cause-report.json",
            invocation_conditions=["issue-and-repository-present"],
            dependencies=["repository-search"],
            failure_modes=["INSUFFICIENT_EVIDENCE"],
            permissions=["repo.read"],
            security_boundary="L0 read-only, network denied",
            reuse_value="Reusable for defect investigation",
            lifecycle_state="PUBLISHED",
        )


def test_published_skill_accepts_pinned_source_role_permissions_and_evals() -> None:
    manifest = SkillManifest(
        name="debugging-and-error-recovery",
        version="1.0.0+upstream.abc1234",
        skill_type="external-skill",
        scenarios=["bug-triage"],
        input_schema="schemas/debugging-input.json",
        output_schema="schemas/root-cause-report.json",
        invocation_conditions=["issue-and-repository-present"],
        dependencies=["repository-search"],
        failure_modes=["INSUFFICIENT_EVIDENCE"],
        permissions=["repo.read"],
        security_boundary="L0 read-only, network denied",
        reuse_value="Reusable for defect investigation",
        source=SkillSource(
            repository="https://github.com/addyosmani/agent-skills",
            path="skills/debugging-and-error-recovery",
            commit="a" * 40,
            license="MIT",
            content_hash=f"sha256:{'b' * 64}",
        ),
        compatible_agents=["agentloom-investigator"],
        allowed_tools=["repository-search:repo.read"],
        allowed_paths=["src/**", "tests/**"],
        risk_level="L0",
        evaluation=SkillEvaluation(
            upstream_evidence_refs=["ev-upstream-debugging"],
            agentloom_bench_evidence_refs=["ev-agentloom-debugging"],
        ),
        lifecycle_state="PUBLISHED",
    )

    assert manifest.source is not None
    assert manifest.source.content_hash == f"sha256:{'b' * 64}"


def test_evidence_requires_sha256_digest() -> None:
    with pytest.raises(ValidationError):
        EvidenceRecord(
            evidence_id="ev-test",
            task_id="task-01",
            step_id="verify-01",
            kind="TEST_OUTPUT",
            producer="agentloom-verifier",
            uri="artifacts/task-01/test.log",
            sha256="not-a-digest",
            summary="tests passed",
        )


def test_passed_verification_requires_all_mandatory_checks() -> None:
    with pytest.raises(ValidationError):
        VerificationResult(
            task_id="task-01",
            patch_hash="a" * 64,
            verdict="PASSED",
            checks=VerificationChecks(
                original_failure_reproduced=True,
                target_tests_passed=True,
                regression_tests_passed=False,
                static_checks_passed=True,
                unauthorized_changes=False,
            ),
            evidence_refs=["ev-test-before", "ev-patch", "ev-test-after"],
            reason="regression failed",
            verifier_agent="agentloom-verifier",
        )


def test_grant_expiry_must_follow_issue_time() -> None:
    issued_at = datetime.now(UTC)
    with pytest.raises(ValidationError):
        SkillExecutionGrant(
            grant_id="grant-01",
            task_id="task-01",
            step_id="implement-01",
            agent_name="agentloom-implementer",
            skill_name="test-driven-development",
            skill_version="1.0.0",
            tool_name="test-runner",
            action="process.exec:test",
            parameter_digest="b" * 64,
            risk_level="L1",
            nonce="nonce-01",
            issued_at=issued_at,
            expires_at=issued_at - timedelta(seconds=1),
        )


def make_repair_artifact_bundle() -> RepairArtifactBundle:
    patch_hash = "c" * 64
    return RepairArtifactBundle(
        root_cause=RootCauseReport(
            task_id="task-01",
            summary="Whitespace was not removed before severity normalization.",
            confidence=0.95,
            evidence_refs=["ev-failing-test"],
            repair_constraints=["Only src/severity.py may change."],
        ),
        patch=PatchArtifact(
            task_id="task-01",
            patch_uri="artifact://task-01/repair.patch",
            sha256=patch_hash,
            changed_paths=["src/severity.py"],
            evidence_refs=["ev-patch"],
        ),
        verification=VerificationResult(
            task_id="task-01",
            patch_hash=patch_hash,
            verdict="PASSED",
            checks=VerificationChecks(
                original_failure_reproduced=True,
                target_tests_passed=True,
                regression_tests_passed=True,
                static_checks_passed=True,
                unauthorized_changes=False,
            ),
            evidence_refs=["ev-failing-test", "ev-patch", "ev-passing-test"],
            reason="The target and regression tests pass in a clean copy.",
            verifier_agent="agentloom-verifier",
        ),
        risk=RiskReport(
            task_id="task-01",
            risk_level="L1",
            verdict="PASSED",
            findings=[
                Finding(
                    rule_id="PATCH_SCOPE",
                    severity="INFO",
                    message="Only the allowlisted source file changed.",
                    location="src/severity.py",
                )
            ],
            evidence_refs=["ev-patch", "ev-passing-test"],
        ),
    )


def test_repair_artifact_bundle_accepts_consistent_role_outputs() -> None:
    bundle = make_repair_artifact_bundle()

    assert bundle.root_cause.task_id == "task-01"
    assert bundle.patch.sha256 == bundle.verification.patch_hash
    assert bundle.risk.verdict == "PASSED"


def test_repair_artifact_bundle_rejects_mixed_task_outputs() -> None:
    bundle = make_repair_artifact_bundle()

    with pytest.raises(ValidationError, match="same taskId"):
        RepairArtifactBundle(
            root_cause=bundle.root_cause,
            patch=bundle.patch.model_copy(update={"task_id": "task-other"}),
            verification=bundle.verification,
            risk=bundle.risk,
        )


def test_repair_artifact_bundle_rejects_unverified_patch_hash() -> None:
    bundle = make_repair_artifact_bundle()

    with pytest.raises(ValidationError, match="patch hash"):
        RepairArtifactBundle(
            root_cause=bundle.root_cause,
            patch=bundle.patch,
            verification=bundle.verification.model_copy(
                update={"patch_hash": "d" * 64}
            ),
            risk=bundle.risk,
        )
