from collections.abc import AsyncIterator
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
