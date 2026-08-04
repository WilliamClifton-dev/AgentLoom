from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from agentloom.api import create_app
from agentloom.contracts import (
    AgentIdentity,
    SkillEvaluation,
    SkillExecutionGrant,
    SkillManifest,
    SkillSource,
)
from agentloom.policy import InMemoryNonceStore, SkillGrantAuthorizer
from agentloom.storage import Database


def authorizer() -> SkillGrantAuthorizer:
    return SkillGrantAuthorizer(
        b"test-signing-key-with-32-bytes!!",
        InMemoryNonceStore(),
    )


def signed_grant(grant_authorizer: SkillGrantAuthorizer) -> dict[str, object]:
    issued_at = datetime.now(UTC)
    grant = SkillExecutionGrant(
        grant_id="grant-api-01",
        task_id="task-01",
        step_id="implement-01",
        agent_name="agentloom-implementer",
        skill_name="test-driven-development",
        skill_version="1.0.0",
        skill_content_hash=f"sha256:{'b' * 64}",
        tool_name="test-runner",
        action="process.exec:test",
        parameter_digest="b" * 64,
        risk_level="L1",
        nonce="nonce-api-01",
        issued_at=issued_at,
        expires_at=issued_at + timedelta(minutes=5),
    )
    manifest = SkillManifest(
        name="test-driven-development",
        version="1.0.0",
        skill_type="external-skill",
        scenarios=["bug-fix"],
        input_schema="schemas/tdd-input.json",
        output_schema="schemas/patch-artifact.json",
        invocation_conditions=["root-cause-confirmed"],
        dependencies=["test-runner"],
        failure_modes=["TEST_FAILED"],
        permissions=["repo.write", "tests.execute"],
        security_boundary="L1 isolated workspace",
        reuse_value="Reusable for bounded repairs",
        source=SkillSource(
            repository="https://github.com/addyosmani/agent-skills",
            path="skills/test-driven-development",
            commit="a" * 40,
            license="MIT",
            content_hash=f"sha256:{'b' * 64}",
        ),
        compatible_agents=["agentloom-implementer"],
        allowed_tools=["test-runner:process.exec:test"],
        allowed_paths=["src/parser.py"],
        risk_level="L1",
        evaluation=SkillEvaluation(
            upstream_evidence_refs=["ev-upstream-tdd"],
            agentloom_bench_evidence_refs=["ev-agentloom-tdd"],
        ),
        lifecycle_state="PUBLISHED",
    )
    agent = AgentIdentity(
        name="agentloom-implementer",
        role="bounded patch implementation",
        capabilities=["repo.write", "tests.execute"],
        inputs=["RootCauseReport"],
        outputs=["PatchArtifact"],
        dependencies=["test-driven-development"],
        decision_boundary=["cannot approve own patch"],
        trace=["tool calls"],
    )
    return grant_authorizer.issue(
        grant,
        manifest=manifest,
        agent=agent,
        requested_paths=["src/parser.py"],
        task_allowed_paths=["src/parser.py"],
        valid_approval_refs=set(),
    ).model_dump(mode="json", by_alias=True)


@pytest.mark.asyncio
async def test_internal_policy_api_verifies_grant_once(tmp_path: Path) -> None:
    grant_authorizer = authorizer()
    database = Database(f"sqlite:///{tmp_path / 'agentloom.db'}")
    database.create_schema()
    transport = httpx.ASGITransport(app=create_app(database, grant_authorizer))
    request = {
        "signedGrant": signed_grant(grant_authorizer),
        "parameterDigest": "b" * 64,
    }

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        accepted = await client.post("/internal/policy/grants/verify", json=request)
        replayed = await client.post("/internal/policy/grants/verify", json=request)

    assert accepted.status_code == 200
    assert accepted.json()["grantId"] == "grant-api-01"
    assert replayed.status_code == 403
    assert replayed.json()["error"]["code"] == "POLICY_DENIED"


@pytest.mark.asyncio
async def test_internal_policy_api_rejects_parameter_mismatch(tmp_path: Path) -> None:
    grant_authorizer = authorizer()
    database = Database(f"sqlite:///{tmp_path / 'agentloom.db'}")
    database.create_schema()
    transport = httpx.ASGITransport(app=create_app(database, grant_authorizer))

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/internal/policy/grants/verify",
            json={
                "signedGrant": signed_grant(grant_authorizer),
                "parameterDigest": "c" * 64,
            },
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "POLICY_DENIED"
