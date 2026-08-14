from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from agentloom.contracts import (
    AgentIdentity,
    ApprovalDecisionRequest,
    ApprovalRecord,
    CoordinationEvent,
    CoordinationTrace,
    DetectionResult,
    EvidenceRecord,
    ExperienceRecord,
    Finding,
    PatchArtifact,
    RepairArtifactBundle,
    RiskReport,
    RootCauseReport,
    SkillEvaluation,
    SkillExecutionGrant,
    SkillManifest,
    SkillSource,
    TaskDetectionRecord,
    TaskEvidenceBundle,
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
            authorized_paths=["tests/test_parser.py"],
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


def make_task_evidence_bundle() -> TaskEvidenceBundle:
    created_at = datetime(2026, 8, 15, tzinfo=UTC)
    evidence = [
        EvidenceRecord(
            evidence_id="ev-static",
            task_id="task-01",
            step_id="implement-static",
            kind="STATIC_PATCH_SCAN",
            producer="agentloom-implementer",
            uri="artifact://task-01/l1-static.json",
            sha256="1" * 64,
            summary="Patch content and changed paths passed static checks.",
            created_at=created_at,
        ),
        EvidenceRecord(
            evidence_id="ev-dynamic",
            task_id="task-01",
            step_id="implement-dynamic",
            kind="DYNAMIC_TEST_RUN",
            producer="agentloom-implementer",
            uri="artifact://task-01/l2-dynamic.txt",
            sha256="2" * 64,
            summary="Allowlisted tests passed in the Implementer workspace.",
            created_at=created_at,
        ),
        EvidenceRecord(
            evidence_id="ev-verification",
            task_id="task-01",
            step_id="verify-01",
            kind="INDEPENDENT_VERIFICATION",
            producer="agentloom-verifier",
            uri="artifact://task-01/l3-verification.txt",
            sha256="3" * 64,
            summary="Clean-workspace verification and hidden tests passed.",
            created_at=created_at,
        ),
    ]
    detections = [
        TaskDetectionRecord(
            detection_id="detection-static",
            task_id="task-01",
            step_id="implement-static",
            producer_agent="agentloom-implementer",
            subject_digest="a" * 64,
            result=DetectionResult(
                stage="STATIC",
                verdict="PASSED",
                findings=[],
                evidence_refs=["ev-static"],
                detector_versions={"patch-scope": "1.0.0"},
            ),
            created_at=created_at,
        ),
        TaskDetectionRecord(
            detection_id="detection-dynamic",
            task_id="task-01",
            step_id="implement-dynamic",
            producer_agent="agentloom-implementer",
            subject_digest="a" * 64,
            result=DetectionResult(
                stage="DYNAMIC",
                verdict="PASSED",
                findings=[],
                evidence_refs=["ev-dynamic"],
                detector_versions={"bounded-pytest": "1.0.0"},
            ),
            created_at=created_at,
        ),
        TaskDetectionRecord(
            detection_id="detection-verification",
            task_id="task-01",
            step_id="verify-01",
            producer_agent="agentloom-verifier",
            subject_digest="a" * 64,
            result=DetectionResult(
                stage="VERIFICATION",
                verdict="PASSED",
                findings=[],
                evidence_refs=["ev-verification"],
                detector_versions={"independent-verifier": "1.0.0"},
            ),
            created_at=created_at,
        ),
    ]
    experience = ExperienceRecord(
        experience_id="experience-01",
        task_id="task-01",
        outcome="SUCCEEDED",
        verdict="PASSED",
        skill_versions={},
        lessons=["Keep static, dynamic, and independent verification separate."],
        evidence_refs=["ev-static", "ev-dynamic", "ev-verification"],
        created_at=created_at,
    )
    return TaskEvidenceBundle(
        task_id="task-01",
        detections=detections,
        evidence=evidence,
        experience=experience,
    )


def test_task_evidence_bundle_binds_three_layers_roles_and_final_evidence() -> None:
    bundle = make_task_evidence_bundle()

    assert [record.result.stage for record in bundle.detections] == [
        "STATIC",
        "DYNAMIC",
        "VERIFICATION",
    ]
    assert bundle.experience.evidence_refs == [
        "ev-static",
        "ev-dynamic",
        "ev-verification",
    ]


def test_task_evidence_bundle_rejects_cross_task_and_missing_evidence() -> None:
    bundle = make_task_evidence_bundle()

    with pytest.raises(ValidationError, match="same taskId"):
        TaskEvidenceBundle(
            task_id=bundle.task_id,
            detections=[
                bundle.detections[0].model_copy(update={"task_id": "task-other"}),
                *bundle.detections[1:],
            ],
            evidence=bundle.evidence,
            experience=bundle.experience,
        )
    with pytest.raises(ValidationError, match="unresolved Evidence"):
        TaskEvidenceBundle(
            task_id=bundle.task_id,
            detections=bundle.detections,
            evidence=[
                *bundle.evidence[:-1],
                bundle.evidence[-1].model_copy(
                    update={"evidence_id": "ev-unrelated"}
                ),
            ],
            experience=bundle.experience,
        )


def test_task_detection_record_enforces_implementer_verifier_separation() -> None:
    record = make_task_evidence_bundle().detections[2]

    with pytest.raises(ValidationError, match="VERIFICATION.*agentloom-verifier"):
        TaskDetectionRecord(
            **record.model_dump(exclude={"producer_agent"}),
            producer_agent="agentloom-implementer",
        )


def test_task_evidence_bundle_rejects_incomplete_final_evidence() -> None:
    bundle = make_task_evidence_bundle()
    incomplete = bundle.experience.model_copy(
        update={"evidence_refs": ["ev-verification"]}
    )

    with pytest.raises(ValidationError, match="every stage Evidence"):
        TaskEvidenceBundle(
            task_id=bundle.task_id,
            detections=bundle.detections,
            evidence=bundle.evidence,
            experience=incomplete,
        )


def test_task_evidence_bundle_rejects_evidence_reused_across_layers() -> None:
    bundle = make_task_evidence_bundle()
    reused_dynamic = bundle.detections[1].model_copy(
        update={
            "result": bundle.detections[1].result.model_copy(
                update={"evidence_refs": ["ev-static"]}
            )
        }
    )

    with pytest.raises(ValidationError, match="distinct Evidence"):
        TaskEvidenceBundle(
            task_id=bundle.task_id,
            detections=[bundle.detections[0], reused_dynamic, bundle.detections[2]],
            evidence=bundle.evidence,
            experience=bundle.experience,
        )


@pytest.mark.parametrize(
    ("outcome", "verdict", "failure_mode"),
    [
        ("SUCCEEDED", "FAILED", "tests failed"),
        ("FAILED", "PASSED", "unexpected success"),
        ("UNCERTAIN", "UNCERTAIN", None),
    ],
)
def test_experience_record_rejects_inconsistent_terminal_outcomes(
    outcome: str,
    verdict: str,
    failure_mode: str | None,
) -> None:
    with pytest.raises(ValidationError, match="outcome"):
        ExperienceRecord(
            experience_id="experience-invalid",
            task_id="task-01",
            outcome=outcome,
            verdict=verdict,
            skill_versions={},
            failure_mode=failure_mode,
            lessons=["Retain the terminal evidence."],
            evidence_refs=["ev-terminal"],
            created_at=datetime(2026, 8, 15, tzinfo=UTC),
        )


@pytest.mark.parametrize(
    ("outcome", "verdict", "failure_mode"),
    [
        ("FAILED", "FAILED", "target tests failed"),
        ("FAILED", "UNSAFE", "scope violation"),
        ("UNCERTAIN", "UNCERTAIN", "detector unavailable"),
    ],
)
def test_experience_record_supports_failed_and_uncertain_outcomes(
    outcome: str,
    verdict: str,
    failure_mode: str,
) -> None:
    record = ExperienceRecord(
        experience_id=f"experience-{outcome.lower()}-{verdict.lower()}",
        task_id="task-01",
        outcome=outcome,
        verdict=verdict,
        skill_versions={},
        failure_mode=failure_mode,
        lessons=["Retain the terminal evidence."],
        evidence_refs=["ev-terminal"],
        created_at=datetime(2026, 8, 15, tzinfo=UTC),
    )

    assert record.failure_mode == failure_mode
def test_grant_issuance_request_rejects_server_owned_fields() -> None:
    from agentloom.contracts import GrantIssuanceRequest

    valid = {
        "taskId": "task-01",
        "stepId": "verify-01",
        "skillName": "code-review-and-quality",
        "skillVersion": "1.0.0",
        "toolName": "test-runner",
        "action": "process.exec:test",
        "parameterDigest": "a" * 64,
        "requestedPaths": ["tests/test_parser.py"],
    }

    request = GrantIssuanceRequest.model_validate(valid)
    assert request.task_id == "task-01"

    for server_owned in (
        "agentName",
        "grantId",
        "nonce",
        "issuedAt",
        "expiresAt",
        "skillContentHash",
        "riskLevel",
    ):
        with pytest.raises(ValidationError, match="extra_forbidden"):
            GrantIssuanceRequest.model_validate({**valid, server_owned: "forged"})
