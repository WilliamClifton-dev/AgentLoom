"""Pinned Docker implementation of the isolated SandboxProvider contract."""

from __future__ import annotations

import asyncio
import hashlib
import re
import subprocess
import time
from collections.abc import Callable
from hmac import compare_digest
from pathlib import Path

from agentloom.bounded_exec import (
    BoundedExecutionError,
    BoundedExecutionOutputLimit,
    BoundedExecutionTimeout,
    run_bounded_command,
)
from agentloom.contracts import SandboxExecutionRequest, SandboxExecutionResult

_IMMUTABLE_IMAGE = re.compile(
    r"^(?:sha256:[a-f0-9]{64}|[a-z0-9][a-z0-9._/-]*@sha256:[a-f0-9]{64})$"
)
_MAX_SNAPSHOT_ENTRIES = 10_000
_MAX_SNAPSHOT_BYTES = 256 * 1024 * 1024

CommandRunner = Callable[
    [tuple[str, ...], Path, int, int],
    subprocess.CompletedProcess[str],
]
CleanupRunner = Callable[[str], None]
_sleep = time.sleep


class SandboxExecutionError(RuntimeError):
    """Raised when an isolated execution cannot produce a trusted result."""


class SandboxExecutionTimeout(SandboxExecutionError):
    """Raised when a sandbox exceeds its signed time budget."""


class SandboxOutputLimit(SandboxExecutionError):
    """Raised when a sandbox exceeds its signed output budget."""


class SandboxSnapshotMismatch(SandboxExecutionError):
    """Raised when the configured workspace does not match the signed snapshot."""


class SandboxCleanupError(SandboxExecutionError):
    """Raised when a temporary sandbox cannot be proven absent."""


def workspace_tree_digest(root: Path) -> str:
    """Hash a bounded regular-file tree, including paths and empty directories."""

    if root.is_symlink() or root.is_junction():
        raise ValueError("sandbox workspace cannot be a symbolic link or junction")
    resolved = root.resolve()
    if not resolved.is_dir():
        raise ValueError("sandbox workspace must be an existing directory")
    digest = hashlib.sha256(b"agentloom.workspace-tree/v1\0")
    entries: list[Path] = []
    for path in resolved.rglob("*"):
        entries.append(path)
        if len(entries) > _MAX_SNAPSHOT_ENTRIES:
            raise ValueError("sandbox workspace contains too many entries")
    entries.sort(key=lambda path: path.relative_to(resolved).as_posix())
    total_bytes = 0
    for path in entries:
        relative = path.relative_to(resolved).as_posix().encode("utf-8")
        if path.is_symlink() or path.is_junction():
            raise ValueError(
                "sandbox workspace cannot contain symbolic links or junctions"
            )
        if path.is_dir():
            digest.update(b"D\0" + relative + b"\0")
            continue
        if not path.is_file():
            raise ValueError("sandbox workspace contains an unsupported file type")
        size = path.stat().st_size
        digest.update(b"F\0" + relative + b"\0" + str(size).encode("ascii") + b"\0")
        bytes_read = 0
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                bytes_read += len(chunk)
                if total_bytes + bytes_read > _MAX_SNAPSHOT_BYTES:
                    raise ValueError("sandbox workspace exceeds the byte limit")
                digest.update(chunk)
        if bytes_read != size:
            raise ValueError("sandbox workspace changed while being hashed")
        total_bytes += bytes_read
    return digest.hexdigest()


class DockerSandboxProvider:
    """Run one signed snapshot in a fresh, tightly constrained Docker container."""

    provider_id = "docker-sandbox"

    def __init__(
        self,
        workspace_root: Path,
        image_ref: str,
        *,
        command_runner: CommandRunner | None = None,
        cleanup_runner: CleanupRunner | None = None,
    ) -> None:
        if workspace_root.is_symlink() or workspace_root.is_junction():
            raise ValueError("sandbox workspace cannot be a symbolic link or junction")
        self._workspace_root = workspace_root.resolve()
        if not self._workspace_root.is_dir():
            raise ValueError("sandbox workspace must be an existing directory")
        if "," in str(self._workspace_root) or "\n" in str(self._workspace_root):
            raise ValueError("sandbox workspace path is incompatible with Docker mounts")
        if not _IMMUTABLE_IMAGE.fullmatch(image_ref):
            raise ValueError("sandbox image must use an immutable image ID or digest")
        self.image_ref = image_ref
        self._command_runner = command_runner or self._run_command
        self._cleanup_runner = cleanup_runner or self._cleanup_container

    async def execute(
        self,
        request: SandboxExecutionRequest,
    ) -> SandboxExecutionResult:
        return await asyncio.to_thread(self._execute, request)

    def _execute(self, request: SandboxExecutionRequest) -> SandboxExecutionResult:
        expected_uri = self._workspace_root.as_uri()
        before_digest = self._snapshot_digest()
        if request.snapshot_uri != expected_uri or not compare_digest(
            request.snapshot_digest,
            before_digest,
        ):
            raise SandboxSnapshotMismatch("sandbox snapshot does not match the signed digest")
        container_name = f"agentloom-{request.execution_id}"
        command = self._docker_command(request, container_name)
        try:
            try:
                completed = self._command_runner(
                    command,
                    self._workspace_root,
                    request.timeout_seconds,
                    request.output_limit_bytes,
                )
            except BoundedExecutionTimeout as exc:
                raise SandboxExecutionTimeout(str(exc)) from exc
            except BoundedExecutionOutputLimit as exc:
                raise SandboxOutputLimit(str(exc)) from exc
            except (BoundedExecutionError, OSError) as exc:
                raise SandboxExecutionError("Docker sandbox execution failed") from exc
        finally:
            self._cleanup_runner(container_name)
        after_digest = self._snapshot_digest()
        if not compare_digest(before_digest, after_digest):
            raise SandboxSnapshotMismatch("sandbox workspace changed during execution")
        return SandboxExecutionResult(
            execution_id=request.execution_id,
            provider_id=self.provider_id,
            image_ref=self.image_ref,
            snapshot_digest=after_digest,
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    def _docker_command(
        self,
        request: SandboxExecutionRequest,
        container_name: str,
    ) -> tuple[str, ...]:
        container_workdir = (
            "/workspace"
            if request.working_directory == "."
            else f"/workspace/{request.working_directory}"
        )
        mount = (
            f"type=bind,source={self._workspace_root},"
            "target=/workspace,readonly"
        )
        return (
            "docker", "run", "--pull", "never", "--rm", "--name", container_name,
            "--network", "none", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges=true", "--user", "65534:65534",
            "--pids-limit", "64", "--memory", "512m", "--memory-swap", "512m",
            "--cpus", "1.0", "--ulimit", "nofile=256:256", "--ulimit", "core=0:0",
            "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m", "--ipc", "none",
            "--hostname", "agentloom-sandbox", "--mount", mount,
            "--workdir", container_workdir, "--env", "HOME=/tmp",
            "--env", "TMPDIR=/tmp", "--env", "PYTHONDONTWRITEBYTECODE=1",
            "--env", "PYTHONNOUSERSITE=1", "--env", "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1",
            "--label", f"agentloom.execution-id={request.execution_id}",
            self.image_ref, *request.command,
        )

    def _snapshot_digest(self) -> str:
        try:
            return workspace_tree_digest(self._workspace_root)
        except (OSError, ValueError) as exc:
            raise SandboxSnapshotMismatch(
                "sandbox snapshot could not be verified"
            ) from exc

    @staticmethod
    def _run_command(
        command: tuple[str, ...],
        working_directory: Path,
        timeout_seconds: int,
        output_limit_bytes: int,
    ) -> subprocess.CompletedProcess[str]:
        return run_bounded_command(
            command=command,
            working_directory=working_directory,
            timeout_seconds=timeout_seconds,
            output_limit_bytes=output_limit_bytes,
        )

    def _cleanup_container(self, container_name: str) -> None:
        last_error: Exception | None = None
        for attempt in range(20):
            try:
                run_bounded_command(
                    command=("docker", "rm", "--force", "--volumes", container_name),
                    working_directory=self._workspace_root,
                    timeout_seconds=15,
                    output_limit_bytes=65536,
                )
                inspected = run_bounded_command(
                    command=("docker", "container", "inspect", container_name),
                    working_directory=self._workspace_root,
                    timeout_seconds=15,
                    output_limit_bytes=65536,
                )
            except (BoundedExecutionError, OSError) as exc:
                last_error = exc
            else:
                if self._docker_reports_absent(inspected):
                    return
            if attempt < 19:
                _sleep(0.1)
        raise SandboxCleanupError(
            "sandbox cleanup could not be verified"
        ) from last_error

    @staticmethod
    def _docker_reports_absent(completed: subprocess.CompletedProcess[str]) -> bool:
        if completed.returncode == 0:
            return False
        output = f"{completed.stdout}\n{completed.stderr}".lower()
        return "no such container" in output or "no such object" in output
