from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from agentloom.api import create_app
from agentloom.storage import Database

INTERNAL_API_TOKEN = "local-test-internal-api-token-32-bytes-minimum"


@pytest_asyncio.fixture
async def client(tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    database = Database(f"sqlite:///{tmp_path / 'agentloom.db'}")
    database.create_schema()
    transport = httpx.ASGITransport(
        app=create_app(database, internal_api_token=INTERNAL_API_TOKEN)
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as api_client:
        yield api_client


def task_payload(title: str = "Fix parser regression") -> dict[str, object]:
    return {
        "title": title,
        "repositoryUri": "fixture://buggy-python-service",
        "issue": "Parser returns None for an empty-but-valid document.",
        "acceptanceCriteria": ["target test passes", "regression tests pass"],
        "allowedPaths": ["src/parser.py", "tests/test_parser.py"],
    }


@pytest.mark.asyncio
async def test_create_and_list_task(client: httpx.AsyncClient) -> None:
    created_response = await client.post("/api/tasks", json=task_payload())

    assert created_response.status_code == 201
    created = created_response.json()
    assert created["status"] == "RECEIVED"
    assert created["planVersion"] == 0
    assert created["title"] == "Fix parser regression"

    listed_response = await client.get("/api/tasks?page=1&pageSize=20")
    assert listed_response.status_code == 200
    listed = listed_response.json()
    assert listed["data"] == [created]
    assert listed["pagination"] == {
        "page": 1,
        "pageSize": 20,
        "totalItems": 1,
        "totalPages": 1,
    }


@pytest.mark.asyncio
async def test_list_tasks_is_paginated(client: httpx.AsyncClient) -> None:
    for index in range(3):
        response = await client.post("/api/tasks", json=task_payload(f"Task {index}"))
        assert response.status_code == 201

    response = await client.get("/api/tasks?page=2&pageSize=2")

    assert response.status_code == 200
    body = response.json()
    assert len(body["data"]) == 1
    assert body["pagination"]["totalItems"] == 3
    assert body["pagination"]["totalPages"] == 2


@pytest.mark.asyncio
async def test_get_missing_task_returns_structured_error(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/api/tasks/missing")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "TASK_NOT_FOUND",
            "message": "Task 'missing' was not found.",
            "details": {"taskId": "missing"},
        }
    }


@pytest.mark.asyncio
async def test_create_task_rejects_unknown_fields(client: httpx.AsyncClient) -> None:
    payload = task_payload()
    payload["untrusted"] = "ignored by loose schemas"

    response = await client.post("/api/tasks", json=payload)

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "authorization",
    [None, "Bearer invalid-token", "Basic invalid-token", b"Bearer \xff"],
)
async def test_internal_task_transition_requires_bearer_token(
    client: httpx.AsyncClient,
    authorization: str | bytes | None,
) -> None:
    created = (await client.post("/api/tasks", json=task_payload())).json()
    headers: dict[str, str] | dict[bytes, bytes]
    if isinstance(authorization, bytes):
        headers = {b"Authorization": authorization}
    elif authorization is None:
        headers = {}
    else:
        headers = {"Authorization": authorization}

    response = await client.post(
        f"/internal/tasks/{created['taskId']}/transitions",
        headers=headers,
        json={
            "expectedPlanVersion": 0,
            "status": "PLANNED",
            "reason": "Coordinator produced a plan.",
        },
    )

    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "INTERNAL_AUTHENTICATION_REQUIRED",
            "message": "A valid internal API bearer token is required.",
            "details": {},
        }
    }


def test_internal_api_rejects_short_tokens(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'agentloom.db'}")
    database.create_schema()

    with pytest.raises(ValueError, match="at least 32 ASCII characters"):
        create_app(database, internal_api_token="short")

    with pytest.raises(ValueError, match="at least 32 ASCII characters"):
        create_app(database, internal_api_token="这是一个超过三十二字符的中文认证密钥")


@pytest.mark.asyncio
async def test_task_transition_advances_state_and_plan_version(
    client: httpx.AsyncClient,
) -> None:
    created = (await client.post("/api/tasks", json=task_payload())).json()

    response = await client.post(
        f"/internal/tasks/{created['taskId']}/transitions",
        headers={"Authorization": f"Bearer {INTERNAL_API_TOKEN}"},
        json={
            "expectedPlanVersion": 0,
            "status": "PLANNED",
            "reason": "Coordinator produced an evidence-bound plan.",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "PLANNED"
    assert response.json()["planVersion"] == 1


@pytest.mark.asyncio
async def test_task_transition_rejects_stale_plan_version(
    client: httpx.AsyncClient,
) -> None:
    created = (await client.post("/api/tasks", json=task_payload())).json()
    endpoint = f"/internal/tasks/{created['taskId']}/transitions"
    request = {
        "expectedPlanVersion": 0,
        "status": "PLANNED",
        "reason": "Coordinator produced a plan.",
    }
    assert (
        await client.post(
            endpoint,
            headers={"Authorization": f"Bearer {INTERNAL_API_TOKEN}"},
            json=request,
        )
    ).status_code == 200

    response = await client.post(
        endpoint,
        headers={"Authorization": f"Bearer {INTERNAL_API_TOKEN}"},
        json={**request, "status": "INVESTIGATING"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "VERSION_CONFLICT"
    assert response.json()["error"]["details"]["currentPlanVersion"] == 1


@pytest.mark.asyncio
async def test_task_transition_rejects_invalid_state_edge(
    client: httpx.AsyncClient,
) -> None:
    created = (await client.post("/api/tasks", json=task_payload())).json()

    response = await client.post(
        f"/internal/tasks/{created['taskId']}/transitions",
        headers={"Authorization": f"Bearer {INTERNAL_API_TOKEN}"},
        json={
            "expectedPlanVersion": 0,
            "status": "COMPLETED",
            "reason": "Attempt to bypass mandatory verification.",
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


@pytest.mark.asyncio
async def test_task_can_finish_as_cancelled_after_approval_rejection(
    client: httpx.AsyncClient,
) -> None:
    created = (await client.post("/api/tasks", json=task_payload())).json()
    endpoint = f"/internal/tasks/{created['taskId']}/transitions"
    transitions = [
        "PLANNED",
        "INVESTIGATING",
        "IMPLEMENTING",
        "AWAITING_APPROVAL",
        "LEARNING",
        "CANCELLED",
    ]

    current = created
    for status in transitions:
        response = await client.post(
            endpoint,
            headers={"Authorization": f"Bearer {INTERNAL_API_TOKEN}"},
            json={
                "expectedPlanVersion": current["planVersion"],
                "status": status,
                "reason": f"Advance task to {status}.",
            },
        )
        assert response.status_code == 200
        current = response.json()

    assert current["status"] == "CANCELLED"
