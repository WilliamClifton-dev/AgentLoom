"""Governed pytest ToolProvider backed exclusively by a SandboxProvider."""

from __future__ import annotations

from hashlib import sha256
from hmac import compare_digest
from pathlib import Path, PurePosixPath
from uuid import uuid4

from pydantic import Field, ValidationError

from agentloom.capabilities import SandboxProvider
from agentloom.contracts import (
    SandboxExecutionRequest,
    SandboxExecutionResult,
    ToolExecutionRequest,
    ToolExecutionResult,
)
from agentloom.docker_sandbox import (
    SandboxCleanupError,
    SandboxExecutionError,
    SandboxExecutionTimeout,
    SandboxOutputLimit,
    SandboxSnapshotMismatch,
    workspace_tree_digest,
)
from agentloom.local_tools import LocalTestRunnerParameters, pytest_target_paths


class SandboxedTestRunnerParameters(LocalTestRunnerParameters):
    workspace_digest: str = Field(
        alias="workspaceDigest",
        pattern=r"^[a-f0-9]{64}$",
    )


class SandboxedTestRunnerProvider:
    """Execute a signed pytest request only through an isolated backend."""

    def __init__(
        self,
        workspace_root: Path,
        evidence_root: Path,
        sandbox_provider: SandboxProvider,
    ) -> None:
        self._workspace_root = workspace_root.resolve()
        if not self._workspace_root.is_dir():
            raise ValueError("test runner workspace root must be an existing directory")
        self._evidence_root = evidence_root.resolve()
        self._sandbox_provider = sandbox_provider
        self.provider_id = f"sandboxed-test-runner/{sandbox_provider.provider_id}"

    def requested_paths(self, request: ToolExecutionRequest) -> list[str]:
        parameters = SandboxedTestRunnerParameters.model_validate(request.parameters)
        self._resolve_working_directory(parameters.working_directory)
        try:
            self._assert_workspace_digest(parameters.workspace_digest)
        except SandboxSnapshotMismatch as exc:
            raise ValueError(str(exc)) from exc
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
        evidence_id = f"ev-tool-{uuid4().hex}"
        if request.tool_name != "test-runner" or request.action != "process.exec:test":
            return self._write_result(
                evidence_id,
                "DENIED",
                "TOOL_ACTION_NOT_SUPPORTED",
                "Tool request is not supported by the sandboxed test runner.\n",
            )
        try:
            parameters = SandboxedTestRunnerParameters.model_validate(request.parameters)
            self._resolve_working_directory(parameters.working_directory)
        except (ValidationError, ValueError) as exc:
            return self._write_result(
                evidence_id,
                "DENIED",
                "INVALID_TOOL_PARAMETERS",
                f"Tool parameters were rejected: {exc}\n",
            )
        try:
            self._assert_workspace_digest(parameters.workspace_digest)
        except SandboxSnapshotMismatch as exc:
            return self._write_result(
                evidence_id,
                "DENIED",
                "SNAPSHOT_MISMATCH",
                f"{exc}\n",
            )

        execution_id = f"sandbox-{uuid4().hex}"
        execution_request = SandboxExecutionRequest(
            execution_id=execution_id,
            snapshot_uri=self._workspace_root.as_uri(),
            snapshot_digest=parameters.workspace_digest,
            command=self._normalized_command(parameters.command),
            working_directory=parameters.working_directory,
            timeout_seconds=parameters.timeout_seconds,
            output_limit_bytes=parameters.output_limit_bytes,
        )
        try:
            result = await self._sandbox_provider.execute(execution_request)
        except SandboxExecutionTimeout as exc:
            return self._write_result(evidence_id, "FAILED", "TOOL_TIMEOUT", f"{exc}\n")
        except SandboxOutputLimit as exc:
            return self._write_result(
                evidence_id,
                "FAILED",
                "OUTPUT_LIMIT_EXCEEDED",
                f"{exc}\n",
            )
        except SandboxSnapshotMismatch as exc:
            return self._write_result(
                evidence_id,
                "FAILED",
                "SNAPSHOT_MISMATCH",
                f"{exc}\n",
            )
        except SandboxCleanupError as exc:
            return self._write_result(
                evidence_id,
                "FAILED",
                "SANDBOX_CLEANUP_FAILED",
                f"{exc}\n",
            )
        except SandboxExecutionError as exc:
            return self._write_result(
                evidence_id,
                "FAILED",
                "TOOL_EXECUTION_FAILED",
                f"{exc}\n",
            )

        if (
            result.execution_id != execution_id
            or result.provider_id != self._sandbox_provider.provider_id
            or not compare_digest(result.snapshot_digest, parameters.workspace_digest)
        ):
            return self._write_result(
                evidence_id,
                "FAILED",
                "SANDBOX_RESULT_MISMATCH",
                "Sandbox result does not match the execution request.\n",
            )
        status = "SUCCEEDED" if result.exit_code == 0 else "FAILED"
        error_code = None if result.exit_code == 0 else "TEST_FAILED"
        return self._write_execution_result(evidence_id, status, error_code, result)

    def _assert_workspace_digest(self, expected: str) -> None:
        try:
            actual = workspace_tree_digest(self._workspace_root)
        except (OSError, ValueError) as exc:
            raise SandboxSnapshotMismatch(
                "workspaceDigest could not be verified"
            ) from exc
        if not compare_digest(actual, expected):
            raise SandboxSnapshotMismatch(
                "workspaceDigest does not match the configured workspace"
            )

    def _resolve_working_directory(self, relative: str) -> Path:
        resolved = (
            self._workspace_root
            if relative == "."
            else (self._workspace_root / relative).resolve()
        )
        if not resolved.is_relative_to(self._workspace_root) or not resolved.is_dir():
            raise ValueError("workingDirectory is outside the configured workspace")
        return resolved

    @staticmethod
    def _normalized_command(command: list[str]) -> list[str]:
        if command[:3] == ["python", "-m", "pytest"]:
            return list(command)
        return ["python", "-m", "pytest", *command[1:]]

    def _write_execution_result(
        self,
        evidence_id: str,
        status: str,
        error_code: str | None,
        result: SandboxExecutionResult,
    ) -> ToolExecutionResult:
        body = (
            f"SANDBOX_PROVIDER: {result.provider_id}\n"
            f"IMAGE_REF: {result.image_ref}\n"
            f"SNAPSHOT_DIGEST: {result.snapshot_digest}\n"
            f"EXIT_CODE: {result.exit_code}\n"
            "STDOUT:\n"
            f"{result.stdout}\n"
            "STDERR:\n"
            f"{result.stderr}\n"
        )
        return self._write_result(evidence_id, status, error_code, body)

    def _write_result(
        self,
        evidence_id: str,
        status: str,
        error_code: str | None,
        body: str,
    ) -> ToolExecutionResult:
        self._evidence_root.mkdir(parents=True, exist_ok=True)
        output_path = self._evidence_root / f"{evidence_id}.txt"
        with output_path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(f"STATUS: {status}\n{body}")
        return ToolExecutionResult(
            status=status,
            evidence_refs=[evidence_id],
            output_digest=sha256(output_path.read_bytes()).hexdigest(),
            error_code=error_code,
        )
