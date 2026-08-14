from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

import pytest

from agentloom.contracts import SandboxExecutionRequest
from agentloom.docker_sandbox import (
    DockerSandboxProvider,
    SandboxExecutionTimeout,
    SandboxOutputLimit,
    workspace_tree_digest,
)

IMAGE_REF = os.environ.get("AGENTLOOM_TEST_SANDBOX_IMAGE")
pytestmark = pytest.mark.skipif(
    IMAGE_REF is None,
    reason="AGENTLOOM_TEST_SANDBOX_IMAGE is not configured",
)


def _image_ref() -> str:
    assert IMAGE_REF is not None
    return IMAGE_REF


def _request(
    workspace: Path,
    execution_id: str,
    target: str,
    *,
    timeout_seconds: int = 15,
    output_limit_bytes: int = 65536,
) -> SandboxExecutionRequest:
    return SandboxExecutionRequest(
        execution_id=execution_id,
        snapshot_uri=workspace.resolve().as_uri(),
        snapshot_digest=workspace_tree_digest(workspace),
        command=["python", "-m", "pytest", "-q", target],
        working_directory=".",
        timeout_seconds=timeout_seconds,
        output_limit_bytes=output_limit_bytes,
    )


def _assert_container_absent(execution_id: str) -> None:
    inspected = subprocess.run(
        ["docker", "container", "inspect", f"agentloom-{execution_id}"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert inspected.returncode != 0


def test_live_sandbox_passes_benign_test_and_enforces_isolation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "test_isolation.py").write_text(
        "import os\n"
        "import socket\n"
        "from pathlib import Path\n"
        "\n"
        "import pytest\n"
        "\n"
        "def test_isolation() -> None:\n"
        "    assert 'AGENTLOOM_LIVE_HOST_SECRET' not in os.environ\n"
        "    with pytest.raises(OSError):\n"
        "        Path('sandbox-write-attempt').write_text('blocked')\n"
        "    with pytest.raises(OSError):\n"
        "        socket.create_connection(('1.1.1.1', 53), timeout=1)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTLOOM_LIVE_HOST_SECRET", "fixture-secret-not-for-container")
    execution_id = "sandbox-1111111111111111"
    provider = DockerSandboxProvider(workspace, _image_ref())

    result = asyncio.run(
        provider.execute(_request(workspace, execution_id, "test_isolation.py"))
    )

    assert result.exit_code == 0
    assert "1 passed" in result.stdout
    assert "fixture-secret-not-for-container" not in result.stdout + result.stderr
    assert not (workspace / "sandbox-write-attempt").exists()
    _assert_container_absent(execution_id)


def test_live_sandbox_enforces_timeout_and_cleans_up(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "test_timeout.py").write_text(
        "import time\n\n"
        "def test_timeout() -> None:\n"
        "    time.sleep(30)\n",
        encoding="utf-8",
    )
    execution_id = "sandbox-2222222222222222"
    provider = DockerSandboxProvider(workspace, _image_ref())

    with pytest.raises(SandboxExecutionTimeout):
        asyncio.run(
            provider.execute(
                _request(
                    workspace,
                    execution_id,
                    "test_timeout.py",
                    timeout_seconds=1,
                )
            )
        )

    _assert_container_absent(execution_id)


def test_live_sandbox_enforces_output_limit_and_cleans_up(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "test_output.py").write_text(
        "def test_output() -> None:\n"
        "    print('x' * 200_000)\n"
        "    assert False\n",
        encoding="utf-8",
    )
    execution_id = "sandbox-3333333333333333"
    provider = DockerSandboxProvider(workspace, _image_ref())

    with pytest.raises(SandboxOutputLimit):
        asyncio.run(
            provider.execute(
                _request(
                    workspace,
                    execution_id,
                    "test_output.py",
                    output_limit_bytes=1024,
                )
            )
        )

    _assert_container_absent(execution_id)
