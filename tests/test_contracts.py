from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from agentloom.contracts import (
    AgentIdentity,
    EvidenceRecord,
    SkillExecutionGrant,
    SkillManifest,
    VerificationChecks,
    VerificationResult,
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
