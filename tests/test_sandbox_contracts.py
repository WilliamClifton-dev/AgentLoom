from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from agentloom.capabilities import SandboxProvider
from agentloom.contracts import SandboxExecutionRequest, SandboxExecutionResult


class StubSandboxProvider:
    provider_id = "stub-sandbox"

    async def execute(
        self,
        request: SandboxExecutionRequest,
    ) -> SandboxExecutionResult:
        return SandboxExecutionResult(
            execution_id=request.execution_id,
            provider_id=self.provider_id,
            image_ref="sha256:" + "b" * 64,
            snapshot_digest=request.snapshot_digest,
            exit_code=0,
            stdout="one passed\n",
            stderr="",
        )


def valid_request(**overrides: object) -> dict[str, object]:
    request: dict[str, object] = {
        "schemaVersion": "agentloom.sandbox-execution/v1alpha1",
        "executionId": "sandbox-0123456789abcdef",
        "snapshotUri": "file:///workspace",
        "snapshotDigest": "a" * 64,
        "command": ["python", "-m", "pytest", "-q", "tests/test_ok.py"],
        "workingDirectory": ".",
        "timeoutSeconds": 30,
        "outputLimitBytes": 65536,
    }
    request.update(overrides)
    return request


def test_sandbox_provider_preserves_versioned_execution_identity() -> None:
    request = SandboxExecutionRequest.model_validate(valid_request())
    provider: SandboxProvider = StubSandboxProvider()

    result = asyncio.run(provider.execute(request))

    assert result.schema_version == "agentloom.sandbox-result/v1alpha1"
    assert result.execution_id == request.execution_id
    assert result.provider_id == "stub-sandbox"
    assert result.snapshot_digest == request.snapshot_digest
    assert result.exit_code == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"schemaVersion": "agentloom.sandbox-execution/v9"},
        {"snapshotDigest": "not-a-digest"},
        {"command": []},
        {"workingDirectory": "../escape"},
        {"timeoutSeconds": 0},
        {"outputLimitBytes": 1024 * 1024 + 1},
        {"unknown": True},
    ],
)
def test_sandbox_execution_request_rejects_unbounded_input(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        SandboxExecutionRequest.model_validate(valid_request(**overrides))
