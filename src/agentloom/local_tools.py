"""Local ToolProvider implementations for the bounded initial runtime."""

import asyncio
from hashlib import sha256
from pathlib import Path, PurePosixPath
from uuid import uuid4

from pydantic import Field, ValidationError, field_validator

from agentloom.bounded_exec import (
    BoundedExecutionError,
    BoundedExecutionOutputLimit,
    BoundedExecutionTimeout,
    run_bounded_python_command,
)
from agentloom.contracts import ContractModel, ToolExecutionRequest, ToolExecutionResult
from agentloom.demo_case import validate_pytest_command


class LocalTestRunnerParameters(ContractModel):
    command: list[str] = Field(min_length=1)
    working_directory: str = Field(alias="workingDirectory", min_length=1)
    timeout_seconds: int = Field(alias="timeoutSeconds", ge=1, le=120)
    output_limit_bytes: int = Field(
        alias="outputLimitBytes", ge=1024, le=1_048_576
    )

    @field_validator("command")
    @classmethod
    def command_is_allowlisted(cls, value: list[str]) -> list[str]:
        command = list(validate_pytest_command(value))
        if not pytest_target_paths(command):
            raise ValueError("pytest command must select at least one test path")
        return command

    @field_validator("working_directory")
    @classmethod
    def working_directory_is_normalized(cls, value: str) -> str:
        if value == ".":
            return value
        if "\\" in value or "\x00" in value:
            raise ValueError("workingDirectory must use safe POSIX syntax")
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
            raise ValueError("workingDirectory must be a normalized relative path")
        return value


class LocalTestRunnerProvider:
    """Execute validated pytest commands inside one configured workspace root."""

    provider_id = "local-test-runner"

    def __init__(self, workspace_root: Path, evidence_root: Path) -> None:
        self._workspace_root = workspace_root.resolve()
        if not self._workspace_root.is_dir():
            raise ValueError("test runner workspace root must be an existing directory")
        self._evidence_root = evidence_root.resolve()

    def requested_paths(self, request: ToolExecutionRequest) -> list[str]:
        parameters = LocalTestRunnerParameters.model_validate(request.parameters)
        self._resolve_working_directory(parameters.working_directory)
        prefix = (
            PurePosixPath()
            if parameters.working_directory == "."
            else PurePosixPath(parameters.working_directory)
        )
        return [
            (prefix / target).as_posix()
            for target in pytest_target_paths(parameters.command)
        ]

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        return await asyncio.to_thread(self._execute, request)

    def _execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        evidence_id = self._evidence_id()
        if request.tool_name != "test-runner" or request.action != "process.exec:test":
            return self._write_result(
                evidence_id=evidence_id,
                status="DENIED",
                error_code="TOOL_ACTION_NOT_SUPPORTED",
                body="Tool request is not supported by the local test runner.\n",
            )
        try:
            parameters = LocalTestRunnerParameters.model_validate(request.parameters)
            working_directory = self._resolve_working_directory(
                parameters.working_directory
            )
        except (ValidationError, ValueError) as exc:
            return self._write_result(
                evidence_id=evidence_id,
                status="DENIED",
                error_code="INVALID_TOOL_PARAMETERS",
                body=f"Tool parameters were rejected: {exc}\n",
            )

        try:
            completed = run_bounded_python_command(
                working_directory=working_directory,
                command=tuple(parameters.command),
                timeout_seconds=parameters.timeout_seconds,
                output_limit_bytes=parameters.output_limit_bytes,
            )
        except BoundedExecutionTimeout as exc:
            return self._write_result(
                evidence_id=evidence_id,
                status="FAILED",
                error_code="TOOL_TIMEOUT",
                body=f"{exc}\n",
            )
        except BoundedExecutionOutputLimit as exc:
            return self._write_result(
                evidence_id=evidence_id,
                status="FAILED",
                error_code="OUTPUT_LIMIT_EXCEEDED",
                body=f"{exc}\n",
            )
        except BoundedExecutionError as exc:
            return self._write_result(
                evidence_id=evidence_id,
                status="FAILED",
                error_code="TOOL_EXECUTION_FAILED",
                body=f"{exc}\n",
            )

        status = "SUCCEEDED" if completed.returncode == 0 else "FAILED"
        error_code = None if completed.returncode == 0 else "TEST_FAILED"
        body = (
            f"EXIT_CODE: {completed.returncode}\n"
            "STDOUT:\n"
            f"{completed.stdout}\n"
            "STDERR:\n"
            f"{completed.stderr}\n"
        )
        return self._write_result(
            evidence_id=evidence_id,
            status=status,
            error_code=error_code,
            body=body,
        )

    def _resolve_working_directory(self, relative: str) -> Path:
        if relative == ".":
            return self._workspace_root
        if "\\" in relative or "\x00" in relative:
            raise ValueError("workingDirectory must use safe POSIX syntax")
        parsed = PurePosixPath(relative)
        if parsed.is_absolute() or ".." in parsed.parts or parsed.as_posix() != relative:
            raise ValueError("workingDirectory must be a normalized relative path")
        resolved = (self._workspace_root / relative).resolve()
        if not resolved.is_relative_to(self._workspace_root) or not resolved.is_dir():
            raise ValueError("workingDirectory is outside the configured workspace")
        return resolved

    def _write_result(
        self,
        *,
        evidence_id: str,
        status: str,
        error_code: str | None,
        body: str,
    ) -> ToolExecutionResult:
        self._evidence_root.mkdir(parents=True, exist_ok=True)
        content = f"STATUS: {status}\n{body}"
        output_path = self._evidence_root / f"{evidence_id}.txt"
        with output_path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        return ToolExecutionResult(
            status=status,
            evidence_refs=[evidence_id],
            output_digest=sha256(output_path.read_bytes()).hexdigest(),
            error_code=error_code,
        )

    @staticmethod
    def _evidence_id() -> str:
        return f"ev-tool-{uuid4().hex}"


def pytest_target_paths(command: list[str]) -> list[str]:
    arguments = (
        command[3:]
        if command[:3] == ["python", "-m", "pytest"]
        else command[1:]
    )
    return [
        argument.split("::", maxsplit=1)[0]
        for argument in arguments
        if not argument.startswith("-")
    ]
