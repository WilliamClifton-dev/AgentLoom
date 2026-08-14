import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from agentloom.contracts import ToolExecutionRequest, tool_parameter_digest
from agentloom.local_tools import LocalTestRunnerProvider


def request_for(parameters: dict[str, object]) -> ToolExecutionRequest:
    return ToolExecutionRequest(
        task_id="task-01",
        step_id="verify-01",
        agent_name="agentloom-verifier",
        skill_name="code-review-and-quality",
        skill_version="1.0.0",
        tool_name="test-runner",
        action="process.exec:test",
        parameter_digest=tool_parameter_digest(parameters),
        parameters=parameters,
    )


def test_tool_request_rejects_parameters_that_do_not_match_digest() -> None:
    with pytest.raises(ValidationError, match="parameters do not match parameterDigest"):
        ToolExecutionRequest(
            task_id="task-01",
            step_id="verify-01",
            agent_name="agentloom-verifier",
            skill_name="code-review-and-quality",
            skill_version="1.0.0",
            tool_name="test-runner",
            action="process.exec:test",
            parameter_digest="a" * 64,
            parameters={"command": ["pytest", "-q"]},
        )


def test_tool_request_rejects_empty_parameters_with_wrong_digest() -> None:
    with pytest.raises(ValidationError, match="parameters do not match parameterDigest"):
        ToolExecutionRequest(
            task_id="task-01",
            step_id="verify-01",
            agent_name="agentloom-verifier",
            skill_name="code-review-and-quality",
            skill_version="1.0.0",
            tool_name="test-runner",
            action="process.exec:test",
            parameter_digest="a" * 64,
            parameters={},
        )


def test_local_test_runner_executes_allowlisted_pytest_and_writes_evidence(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    evidence = tmp_path / "evidence"
    (workspace / "tests").mkdir(parents=True)
    (workspace / "tests" / "test_ok.py").write_text(
        "def test_ok() -> None:\n    assert True\n",
        encoding="utf-8",
    )
    parameters: dict[str, object] = {
        "command": ["pytest", "-q", "tests/test_ok.py"],
        "workingDirectory": ".",
        "timeoutSeconds": 30,
        "outputLimitBytes": 65536,
    }
    provider = LocalTestRunnerProvider(workspace, evidence)

    result = asyncio.run(provider.execute(request_for(parameters)))

    assert result.status == "SUCCEEDED"
    assert result.error_code is None
    assert result.output_digest is not None
    output_files = list(evidence.glob("*.txt"))
    assert len(output_files) == 1
    assert "1 passed" in output_files[0].read_text(encoding="utf-8")


def test_local_test_runner_returns_denied_for_unsafe_command(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    parameters: dict[str, object] = {
        "command": ["powershell", "-Command", "pytest"],
        "workingDirectory": ".",
        "timeoutSeconds": 30,
        "outputLimitBytes": 65536,
    }
    provider = LocalTestRunnerProvider(workspace, tmp_path / "evidence")

    result = asyncio.run(provider.execute(request_for(parameters)))

    assert result.status == "DENIED"
    assert result.error_code == "INVALID_TOOL_PARAMETERS"


def test_local_test_runner_returns_structured_failed_result(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "tests").mkdir(parents=True)
    (workspace / "tests" / "test_failure.py").write_text(
        "def test_failure() -> None:\n    assert False\n",
        encoding="utf-8",
    )
    parameters: dict[str, object] = {
        "command": ["pytest", "-q", "tests/test_failure.py"],
        "workingDirectory": ".",
        "timeoutSeconds": 30,
        "outputLimitBytes": 65536,
    }
    provider = LocalTestRunnerProvider(workspace, tmp_path / "evidence")

    result = asyncio.run(provider.execute(request_for(parameters)))

    assert result.status == "FAILED"
    assert result.error_code == "TEST_FAILED"
    assert result.output_digest is not None


def test_local_test_runner_never_overwrites_evidence_for_repeated_request(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    evidence = tmp_path / "evidence"
    (workspace / "tests").mkdir(parents=True)
    (workspace / "tests" / "test_ok.py").write_text(
        "def test_ok() -> None:\n    assert True\n",
        encoding="utf-8",
    )
    parameters: dict[str, object] = {
        "command": ["pytest", "-q", "tests/test_ok.py"],
        "workingDirectory": ".",
        "timeoutSeconds": 30,
        "outputLimitBytes": 65536,
    }
    provider = LocalTestRunnerProvider(workspace, evidence)
    request = request_for(parameters)

    first = asyncio.run(provider.execute(request))
    second = asyncio.run(provider.execute(request))

    assert first.evidence_refs != second.evidence_refs
    assert len(list(evidence.glob("*.txt"))) == 2
