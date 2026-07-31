from datetime import UTC, datetime, timedelta

import pytest

from agentloom.contracts import (
    AgentIdentity,
    SignedSkillExecutionGrant,
    SkillEvaluation,
    SkillExecutionGrant,
    SkillManifest,
    SkillSource,
)
from agentloom.policy import InMemoryNonceStore, PolicyDenied, SkillGrantAuthorizer

SIGNING_KEY = b"test-signing-key-with-32-bytes!!"


def make_grant(**overrides: object) -> SkillExecutionGrant:
    issued_at = datetime.now(UTC)
    values: dict[str, object] = {
        "grant_id": "grant-01",
        "task_id": "task-01",
        "step_id": "implement-01",
        "agent_name": "agentloom-implementer",
        "skill_name": "test-driven-development",
        "skill_version": "1.0.0",
        "skill_content_hash": f"sha256:{'b' * 64}",
        "tool_name": "test-runner",
        "action": "process.exec:test",
        "parameter_digest": "b" * 64,
        "risk_level": "L1",
        "nonce": "nonce-0001",
        "issued_at": issued_at,
        "expires_at": issued_at + timedelta(minutes=5),
    }
    values.update(overrides)
    return SkillExecutionGrant.model_validate(values)


def make_authorizer() -> SkillGrantAuthorizer:
    return SkillGrantAuthorizer(SIGNING_KEY, InMemoryNonceStore())


def published_manifest(**overrides: object) -> SkillManifest:
    values: dict[str, object] = {
        "name": "test-driven-development",
        "version": "1.0.0",
        "skill_type": "external-skill",
        "scenarios": ["bug-fix"],
        "input_schema": "schemas/tdd-input.json",
        "output_schema": "schemas/patch-artifact.json",
        "invocation_conditions": ["root-cause-confirmed"],
        "dependencies": ["test-runner"],
        "failure_modes": ["TEST_FAILED"],
        "permissions": ["repo.write", "tests.execute"],
        "security_boundary": "L1 isolated workspace",
        "reuse_value": "Reusable for bounded repairs",
        "source": SkillSource(
            repository="https://github.com/addyosmani/agent-skills",
            path="skills/test-driven-development",
            commit="a" * 40,
            license="MIT",
            content_hash=f"sha256:{'b' * 64}",
        ),
        "compatible_agents": ["agentloom-implementer"],
        "allowed_tools": ["test-runner:process.exec:test"],
        "allowed_paths": ["src/parser.py", "tests/test_parser.py"],
        "risk_level": "L1",
        "evaluation": SkillEvaluation(
            upstream_evidence_refs=["ev-upstream-tdd"],
            agentloom_bench_evidence_refs=["ev-agentloom-tdd"],
        ),
        "lifecycle_state": "PUBLISHED",
    }
    values.update(overrides)
    return SkillManifest.model_validate(values)


def implementer_identity() -> AgentIdentity:
    return AgentIdentity(
        name="agentloom-implementer",
        role="bounded patch implementation",
        capabilities=["repo.write", "tests.execute"],
        inputs=["RootCauseReport"],
        outputs=["PatchArtifact"],
        dependencies=["test-driven-development"],
        decision_boundary=["cannot approve own patch"],
        trace=["tool calls", "patch hash"],
    )


def issue_grant(
    authorizer: SkillGrantAuthorizer,
    grant: SkillExecutionGrant | None = None,
    *,
    valid_approval_refs: set[str] | None = None,
) -> SignedSkillExecutionGrant:
    return authorizer.issue(
        grant or make_grant(),
        manifest=published_manifest(),
        agent=implementer_identity(),
        requested_paths=["src/parser.py"],
        task_allowed_paths=["src/parser.py"],
        valid_approval_refs=valid_approval_refs or set(),
    )


def test_valid_grant_is_accepted_once() -> None:
    authorizer = make_authorizer()
    signed = issue_grant(authorizer)

    verified = authorizer.verify(signed, parameter_digest="b" * 64)

    assert verified.grant_id == "grant-01"
    with pytest.raises(PolicyDenied, match="grant nonce has already been used"):
        authorizer.verify(signed, parameter_digest="b" * 64)


def test_parameter_digest_must_match_bound_request() -> None:
    authorizer = make_authorizer()
    signed = issue_grant(authorizer)

    with pytest.raises(PolicyDenied, match="request parameters do not match grant"):
        authorizer.verify(signed, parameter_digest="c" * 64)


def test_tampered_grant_is_rejected() -> None:
    authorizer = make_authorizer()
    signed = issue_grant(authorizer)
    tampered = signed.model_copy(
        update={"grant": signed.grant.model_copy(update={"action": "process.exec:shell"})}
    )

    with pytest.raises(PolicyDenied, match="grant signature is invalid"):
        authorizer.verify(tampered, parameter_digest="b" * 64)


def test_expired_grant_is_rejected() -> None:
    issued_at = datetime.now(UTC) - timedelta(minutes=10)
    issuer = SkillGrantAuthorizer(
        SIGNING_KEY,
        InMemoryNonceStore(),
        clock=lambda: issued_at,
    )
    signed = issue_grant(
        issuer,
        make_grant(
            issued_at=issued_at,
            expires_at=issued_at + timedelta(minutes=5),
        )
    )
    authorizer = make_authorizer()

    with pytest.raises(PolicyDenied, match="grant has expired"):
        authorizer.verify(signed, parameter_digest="b" * 64)


def test_l2_grant_requires_valid_approval_reference() -> None:
    authorizer = make_authorizer()

    with pytest.raises(PolicyDenied, match="L2/L3 grant approval is not valid"):
        issue_grant(
            authorizer,
            make_grant(risk_level="L2", approval_ref="approval-01"),
        )


def test_issue_rejects_unpublished_skill() -> None:
    authorizer = make_authorizer()

    with pytest.raises(PolicyDenied, match="Skill is not published"):
        authorizer.issue(
            make_grant(),
            manifest=published_manifest(lifecycle_state="QUARANTINED"),
            agent=implementer_identity(),
            requested_paths=["src/parser.py"],
            task_allowed_paths=["src/parser.py"],
            valid_approval_refs=set(),
        )


def test_issue_rejects_role_tool_and_path_escalation() -> None:
    authorizer = make_authorizer()
    manifest = published_manifest()

    with pytest.raises(PolicyDenied, match="Agent is not compatible"):
        authorizer.issue(
            make_grant(agent_name="agentloom-verifier"),
            manifest=manifest,
            agent=implementer_identity(),
            requested_paths=["src/parser.py"],
            task_allowed_paths=["src/parser.py"],
            valid_approval_refs=set(),
        )

    with pytest.raises(PolicyDenied, match="Tool action is not allowed"):
        authorizer.issue(
            make_grant(action="process.exec:shell"),
            manifest=manifest,
            agent=implementer_identity(),
            requested_paths=["src/parser.py"],
            task_allowed_paths=["src/parser.py"],
            valid_approval_refs=set(),
        )

    with pytest.raises(PolicyDenied, match="Requested path is not allowed"):
        authorizer.issue(
            make_grant(),
            manifest=manifest,
            agent=implementer_identity(),
            requested_paths=["pyproject.toml"],
            task_allowed_paths=["src/parser.py"],
            valid_approval_refs=set(),
        )


def test_issue_signs_grant_bound_to_published_skill_content() -> None:
    authorizer = make_authorizer()
    manifest = published_manifest()

    signed = authorizer.issue(
        make_grant(skill_content_hash=f"sha256:{'b' * 64}"),
        manifest=manifest,
        agent=implementer_identity(),
        requested_paths=["src/parser.py"],
        task_allowed_paths=["src/parser.py", "tests/test_parser.py"],
        valid_approval_refs=set(),
    )

    assert manifest.source is not None
    assert signed.grant.skill_content_hash == manifest.source.content_hash
