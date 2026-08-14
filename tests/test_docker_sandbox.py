from __future__ import annotations

import asyncio
import os
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

import agentloom.docker_sandbox as docker_sandbox
from agentloom.bounded_exec import BoundedExecutionTimeout
from agentloom.contracts import SandboxExecutionRequest
from agentloom.docker_sandbox import (
    DockerSandboxProvider,
    SandboxCleanupError,
    SandboxExecutionTimeout,
    SandboxSnapshotMismatch,
    workspace_tree_digest,
)

IMAGE_REF = "sha256:" + "b" * 64


class RecordingRunner:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def __call__(
        self,
        command: tuple[str, ...],
        working_directory: Path,
        timeout_seconds: int,
        output_limit_bytes: int,
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        assert working_directory.is_dir()
        assert timeout_seconds == 30
        assert output_limit_bytes == 65536
        return subprocess.CompletedProcess(command, 0, "one passed\n", "")


def sandbox_request(workspace: Path, **overrides: object) -> SandboxExecutionRequest:
    values: dict[str, object] = {
        "executionId": "sandbox-0123456789abcdef",
        "snapshotUri": workspace.resolve().as_uri(),
        "snapshotDigest": workspace_tree_digest(workspace),
        "command": ["python", "-m", "pytest", "-q", "tests/test_ok.py"],
        "workingDirectory": ".",
        "timeoutSeconds": 30,
        "outputLimitBytes": 65536,
    }
    values.update(overrides)
    return SandboxExecutionRequest.model_validate(values)


def create_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / "tests").mkdir(parents=True)
    (workspace / "tests" / "test_ok.py").write_text(
        "def test_ok() -> None:\n    assert True\n",
        encoding="utf-8",
    )
    return workspace


def test_workspace_tree_digest_binds_paths_content_and_empty_directories(
    tmp_path: Path,
) -> None:
    workspace = create_workspace(tmp_path)
    first = workspace_tree_digest(workspace)

    (workspace / "empty").mkdir()
    second = workspace_tree_digest(workspace)
    (workspace / "tests" / "test_ok.py").write_text(
        "def test_ok() -> None:\n    assert False\n",
        encoding="utf-8",
    )
    third = workspace_tree_digest(workspace)

    assert len({first, second, third}) == 3
    assert all(len(digest) == 64 for digest in (first, second, third))


def test_docker_sandbox_uses_fixed_isolation_controls_and_no_host_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = create_workspace(tmp_path)
    runner = RecordingRunner()
    cleaned: list[str] = []
    monkeypatch.setenv("AGENTLOOM_POLICY_SIGNING_KEY", "must-not-enter-container")
    provider = DockerSandboxProvider(
        workspace,
        IMAGE_REF,
        command_runner=runner,
        cleanup_runner=cleaned.append,
    )

    result = asyncio.run(provider.execute(sandbox_request(workspace)))

    assert result.exit_code == 0
    assert result.image_ref == IMAGE_REF
    command = runner.commands[0]
    assert command[:3] == ("docker", "run", "--pull")
    assert "never" in command
    assert ("--network", "none") == command[
        command.index("--network") : command.index("--network") + 2
    ]
    assert "--read-only" in command
    assert ("--cap-drop", "ALL") == command[
        command.index("--cap-drop") : command.index("--cap-drop") + 2
    ]
    assert "no-new-privileges=true" in command
    assert ("--user", "65534:65534") == command[
        command.index("--user") : command.index("--user") + 2
    ]
    assert "type=bind" in " ".join(command)
    assert "readonly" in " ".join(command)
    assert "must-not-enter-container" not in " ".join(command)
    assert command[-5:] == ("python", "-m", "pytest", "-q", "tests/test_ok.py")
    assert cleaned == ["agentloom-sandbox-0123456789abcdef"]


@pytest.mark.parametrize(
    "image_ref",
    ["python:3.12-slim", "latest", "repo@sha256:not-a-digest", ""],
)
def test_docker_sandbox_rejects_mutable_or_invalid_images(
    tmp_path: Path,
    image_ref: str,
) -> None:
    workspace = create_workspace(tmp_path)

    with pytest.raises(ValueError, match="immutable"):
        DockerSandboxProvider(workspace, image_ref)


def test_docker_sandbox_rejects_snapshot_mismatch_before_execution(
    tmp_path: Path,
) -> None:
    workspace = create_workspace(tmp_path)
    runner = RecordingRunner()
    provider = DockerSandboxProvider(
        workspace,
        IMAGE_REF,
        command_runner=runner,
        cleanup_runner=lambda _: None,
    )

    with pytest.raises(SandboxSnapshotMismatch):
        asyncio.run(
            provider.execute(
                sandbox_request(workspace, snapshotDigest="c" * 64),
            )
        )

    assert runner.commands == []


def test_docker_sandbox_maps_unreadable_snapshot_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = create_workspace(tmp_path)
    request = sandbox_request(workspace)
    runner = RecordingRunner()
    provider = DockerSandboxProvider(
        workspace,
        IMAGE_REF,
        command_runner=runner,
        cleanup_runner=lambda _: None,
    )

    def unreadable_snapshot(_: Path) -> str:
        raise ValueError("snapshot became unreadable")

    monkeypatch.setattr(docker_sandbox, "workspace_tree_digest", unreadable_snapshot)

    with pytest.raises(SandboxSnapshotMismatch, match="could not be verified"):
        asyncio.run(provider.execute(request))

    assert runner.commands == []


def test_docker_sandbox_cleans_up_after_timeout(tmp_path: Path) -> None:
    workspace = create_workspace(tmp_path)
    cleaned: list[str] = []

    def timeout_runner(
        command: tuple[str, ...],
        working_directory: Path,
        timeout_seconds: int,
        output_limit_bytes: int,
    ) -> subprocess.CompletedProcess[str]:
        raise BoundedExecutionTimeout("timed out")

    provider = DockerSandboxProvider(
        workspace,
        IMAGE_REF,
        command_runner=timeout_runner,
        cleanup_runner=cleaned.append,
    )

    with pytest.raises(SandboxExecutionTimeout):
        asyncio.run(provider.execute(sandbox_request(workspace)))

    assert cleaned == ["agentloom-sandbox-0123456789abcdef"]


def test_docker_sandbox_fails_when_cleanup_cannot_be_verified(tmp_path: Path) -> None:
    workspace = create_workspace(tmp_path)

    def cleanup_failure(_: str) -> None:
        raise SandboxCleanupError("container still exists")

    provider = DockerSandboxProvider(
        workspace,
        IMAGE_REF,
        command_runner=RecordingRunner(),
        cleanup_runner=cleanup_failure,
    )

    with pytest.raises(SandboxCleanupError, match="container still exists"):
        asyncio.run(provider.execute(sandbox_request(workspace)))


def test_docker_sandbox_retries_cleanup_until_absence_is_verified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = create_workspace(tmp_path)
    responses = iter(
        [
            subprocess.CompletedProcess([], 1, "", "removal already in progress"),
            subprocess.CompletedProcess([], 0, "[{\"State\": {}}]", ""),
            subprocess.CompletedProcess([], 1, "", "No such container"),
            subprocess.CompletedProcess([], 1, "", "No such object"),
        ]
    )

    def run_command(**_: object) -> subprocess.CompletedProcess[str]:
        return next(responses)

    monkeypatch.setattr(docker_sandbox, "run_bounded_command", run_command)
    provider = DockerSandboxProvider(workspace, IMAGE_REF)

    provider._cleanup_container("agentloom-sandbox-0123456789abcdef")


def test_docker_sandbox_does_not_treat_daemon_failure_as_verified_absence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = create_workspace(tmp_path)

    def daemon_failure(**_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 1, "", "daemon unavailable")

    monkeypatch.setattr(docker_sandbox, "run_bounded_command", daemon_failure)
    monkeypatch.setattr(docker_sandbox, "_sleep", lambda _: None)
    provider = DockerSandboxProvider(workspace, IMAGE_REF)

    with pytest.raises(SandboxCleanupError, match="could not be verified"):
        provider._cleanup_container("agentloom-sandbox-0123456789abcdef")


CommandRunner = Callable[
    [tuple[str, ...], Path, int, int],
    subprocess.CompletedProcess[str],
]


def test_test_process_environment_is_not_forwarded_by_docker_arguments(
    tmp_path: Path,
) -> None:
    workspace = create_workspace(tmp_path)
    runner = RecordingRunner()
    provider = DockerSandboxProvider(
        workspace,
        IMAGE_REF,
        command_runner=runner,
        cleanup_runner=lambda _: None,
    )
    original = os.environ.get("AGENTLOOM_GATEWAY_ASSERTION")
    os.environ["AGENTLOOM_GATEWAY_ASSERTION"] = "gateway-secret"
    try:
        asyncio.run(provider.execute(sandbox_request(workspace)))
    finally:
        if original is None:
            os.environ.pop("AGENTLOOM_GATEWAY_ASSERTION", None)
        else:
            os.environ["AGENTLOOM_GATEWAY_ASSERTION"] = original

    assert "gateway-secret" not in " ".join(runner.commands[0])
