from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from agentloom.api import create_app
from agentloom.contracts import SkillExecutionGrant
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
        tool_name="test-runner",
        action="process.exec:test",
        parameter_digest="b" * 64,
        risk_level="L1",
        nonce="nonce-api-01",
        issued_at=issued_at,
        expires_at=issued_at + timedelta(minutes=5),
    )
    return grant_authorizer.sign(grant).model_dump(mode="json", by_alias=True)


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
