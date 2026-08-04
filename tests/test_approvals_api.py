from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from agentloom.api import create_app
from agentloom.storage import Database


@pytest_asyncio.fixture
async def client(tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    database = Database(f"sqlite:///{tmp_path / 'agentloom.db'}")
    database.create_schema()
    transport = httpx.ASGITransport(app=create_app(database))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as api_client:
        yield api_client


def task_payload() -> dict[str, object]:
    return {
        "title": "Approve reviewed pull request",
        "repositoryUri": "fixture://approval-case",
        "issue": "A verified patch requires an external write.",
        "acceptanceCriteria": ["Approval matches exact request parameters."],
        "allowedPaths": ["src/parser.py"],
    }


def approval_payload(task_id: str) -> dict[str, object]:
    return {
        "taskId": task_id,
        "grantId": "grant-api-01",
        "parameterDigest": "a" * 64,
        "riskLevel": "L2",
        "routeId": "github-pr-v1",
        "rollbackPlanHash": "b" * 64,
        "actionSummary": "Create the reviewed pull request.",
        "requestedBy": "agentloom-implementer",
        "expiresAt": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
    }


@pytest.mark.asyncio
async def test_approval_api_creates_reads_and_decides_exact_request(
    client: httpx.AsyncClient,
) -> None:
    task = (await client.post("/api/tasks", json=task_payload())).json()
    created_response = await client.post(
        "/internal/approvals",
        json=approval_payload(task["taskId"]),
    )

    assert created_response.status_code == 201
    pending = created_response.json()
    read_response = await client.get(f"/internal/approvals/{pending['approvalId']}")
    decision_response = await client.post(
        f"/internal/approvals/{pending['approvalId']}/decisions",
        json={
            "expectedApprovalVersion": 0,
            "status": "APPROVED",
            "actor": "agentloom-developer",
            "reason": "Exact request and rollback plan reviewed.",
        },
    )

    assert read_response.status_code == 200
    assert read_response.json() == pending
    assert decision_response.status_code == 200
    assert decision_response.json()["status"] == "APPROVED"
    assert decision_response.json()["approvalVersion"] == 1


@pytest.mark.asyncio
async def test_approval_api_rejects_unknown_task_and_stale_decision(
    client: httpx.AsyncClient,
) -> None:
    missing_response = await client.post(
        "/internal/approvals",
        json=approval_payload("task-missing"),
    )
    assert missing_response.status_code == 404
    assert missing_response.json()["error"]["code"] == "APPROVAL_TASK_NOT_FOUND"

    task = (await client.post("/api/tasks", json=task_payload())).json()
    approval = (
        await client.post("/internal/approvals", json=approval_payload(task["taskId"]))
    ).json()
    endpoint = f"/internal/approvals/{approval['approvalId']}/decisions"
    request = {
        "expectedApprovalVersion": 0,
        "status": "REJECTED",
        "actor": "agentloom-developer",
        "reason": "External write is not approved.",
    }
    assert (await client.post(endpoint, json=request)).status_code == 200
    stale_response = await client.post(endpoint, json={**request, "status": "APPROVED"})

    assert stale_response.status_code == 409
    assert stale_response.json()["error"]["code"] == "APPROVAL_VERSION_CONFLICT"
