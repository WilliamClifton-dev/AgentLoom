from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agentloom.contracts import (
    SandboxExecutionRequest,
    SandboxExecutionResult,
    ToolExecutionRequest,
    tool_parameter_digest,
)
from agentloom.docker_sandbox import SandboxExecutionTimeout, workspace_tree_digest
from agentloom.sandbox_tools import SandboxedTestRunnerProvider

IMAGE_REF = "sha256:" + "d" * 64


class RecordingSandbox:
    provider_id = "recording-sandbox"

    def __init__(self) -> None:
        self.requests: list[SandboxExecutionRequest] = []

    async def execute(
        self,
        request: SandboxExecutionRequest,
    ) -> SandboxExecutionResult:
        self.requests.append(request)
        return SandboxExecutionResult(
            execution_id=request.execution_id,
            provider_id=self.provider_id,
            image_ref=IMAGE_REF,
            snapshot_digest=request.snapshot_digest,
            exit_code=0,
            stdout="one passed\n",
            stderr="",
        )


class TimeoutSandbox:
    provider_id = "timeout-sandbox"

    async def execute(
        self,
        request: SandboxExecutionRequest,
    ) -> SandboxExecutionResult:
        raise SandboxExecutionTimeout("timed out")


def create_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / "tests").mkdir(parents=True)
    (workspace / "tests" / "test_ok.py").write_text(
        "def test_ok() -> None:\n    assert True\n",
        encoding="utf-8",
    )
    return workspace


def parameters_for(workspace: Path, **overrides: object) -> dict[str, object]:
    parameters: dict[str, object] = {
        "command": ["pytest", "-q", "tests/test_ok.py"],
        "workingDirectory": ".",
        "workspaceDigest": workspace_tree_digest(workspace),
        "timeoutSeconds": 30,
        "outputLimitBytes": 65536,
    }
    parameters.update(overrides)
    return parameters


def request_for(parameters: dict[str, object]) -> ToolExecutionRequest:
    return ToolExecutionRequest(
        task_id="task-sandbox",
        step_id="verify-sandbox",
        agent_name="agentloom-verifier",
        skill_name="code-review-and-quality",
        skill_version="1.0.0",
        tool_name="test-runner",
        action="process.exec:test",
        parameter_digest=tool_parameter_digest(parameters),
        parameters=parameters,
    )


def test_sandboxed_runner_binds_snapshot_and_writes_backend_evidence(
    tmp_path: Path,
) -> None:
    workspace = create_workspace(tmp_path)
    evidence = tmp_path / "evidence"
    sandbox = RecordingSandbox()
    provider = SandboxedTestRunnerProvider(workspace, evidence, sandbox)
    parameters = parameters_for(workspace)

    assert provider.requested_paths(request_for(parameters)) == ["tests/test_ok.py"]
    result = asyncio.run(provider.execute(request_for(parameters)))

    assert result.status == "SUCCEEDED"
    assert provider.provider_id == "sandboxed-test-runner/recording-sandbox"
    assert len(sandbox.requests) == 1
    execution = sandbox.requests[0]
    assert execution.snapshot_digest == parameters["workspaceDigest"]
    assert execution.command == [
        "python",
        "-m",
        "pytest",
        "-q",
        "tests/test_ok.py",
    ]
    output = next(evidence.glob("*.txt")).read_text(encoding="utf-8")
    assert "SANDBOX_PROVIDER: recording-sandbox" in output
    assert f"IMAGE_REF: {IMAGE_REF}" in output
    assert f"SNAPSHOT_DIGEST: {parameters['workspaceDigest']}" in output
    assert "one passed" in output


def test_sandboxed_runner_rejects_unsigned_or_stale_workspace_digest(
    tmp_path: Path,
) -> None:
    workspace = create_workspace(tmp_path)
    sandbox = RecordingSandbox()
    provider = SandboxedTestRunnerProvider(workspace, tmp_path / "evidence", sandbox)
    parameters = parameters_for(workspace, workspaceDigest="e" * 64)

    with pytest.raises(ValueError, match="workspaceDigest"):
        provider.requested_paths(request_for(parameters))

    result = asyncio.run(provider.execute(request_for(parameters)))
    assert result.status == "DENIED"
    assert result.error_code == "SNAPSHOT_MISMATCH"
    assert sandbox.requests == []


def test_sandboxed_runner_maps_timeout_without_host_fallback(tmp_path: Path) -> None:
    workspace = create_workspace(tmp_path)
    provider = SandboxedTestRunnerProvider(
        workspace,
        tmp_path / "evidence",
        TimeoutSandbox(),
    )

    result = asyncio.run(provider.execute(request_for(parameters_for(workspace))))

    assert result.status == "FAILED"
    assert result.error_code == "TOOL_TIMEOUT"
    assert len(list((tmp_path / "evidence").glob("*.txt"))) == 1


def test_sandboxed_runner_rejects_missing_workspace_digest(tmp_path: Path) -> None:
    workspace = create_workspace(tmp_path)
    parameters = parameters_for(workspace)
    del parameters["workspaceDigest"]
    provider = SandboxedTestRunnerProvider(
        workspace,
        tmp_path / "evidence",
        RecordingSandbox(),
    )

    result = asyncio.run(provider.execute(request_for(parameters)))

    assert result.status == "DENIED"
    assert result.error_code == "INVALID_TOOL_PARAMETERS"


@pytest.mark.parametrize("working_directory", [r"tests\..", "tests/../tests"])
def test_sandboxed_runner_rejects_non_normalized_working_directory_before_execution(
    tmp_path: Path,
    working_directory: str,
) -> None:
    workspace = create_workspace(tmp_path)
    sandbox = RecordingSandbox()
    provider = SandboxedTestRunnerProvider(workspace, tmp_path / "evidence", sandbox)
    parameters = parameters_for(workspace, workingDirectory=working_directory)

    with pytest.raises(ValueError, match="workingDirectory"):
        provider.requested_paths(request_for(parameters))
    result = asyncio.run(provider.execute(request_for(parameters)))

    assert result.status == "DENIED"
    assert result.error_code == "INVALID_TOOL_PARAMETERS"
    assert sandbox.requests == []
