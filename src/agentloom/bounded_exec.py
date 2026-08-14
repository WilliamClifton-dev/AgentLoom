"""Bounded local execution for allowlisted Python tool providers."""

import os
import subprocess
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import BinaryIO

from agentloom.demo_case import resolve_command

_PASSTHROUGH_ENVIRONMENT = frozenset(
    {
        "COMSPEC",
        "LANG",
        "LC_ALL",
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "WINDIR",
    }
)


class BoundedExecutionError(RuntimeError):
    """Raised when a bounded command cannot produce a trustworthy result."""


class BoundedExecutionTimeout(BoundedExecutionError):
    """Raised when a command exceeds its declared time budget."""


class BoundedExecutionOutputLimit(BoundedExecutionError):
    """Raised when captured output exceeds its declared byte budget."""


def run_bounded_python_command(
    *,
    working_directory: Path,
    command: tuple[str, ...],
    timeout_seconds: int,
    output_limit_bytes: int,
) -> subprocess.CompletedProcess[str]:
    """Run one already-validated Python module command with hard resource limits."""

    resolved = resolve_command(command)
    return run_bounded_command(
        working_directory=working_directory,
        command=tuple(resolved),
        timeout_seconds=timeout_seconds,
        output_limit_bytes=output_limit_bytes,
    )


def run_bounded_command(
    *,
    working_directory: Path,
    command: tuple[str, ...],
    timeout_seconds: int,
    output_limit_bytes: int,
    environment: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run an exact argv with bounded output, time, and a scrubbed environment."""

    if not command or any(not argument or "\x00" in argument for argument in command):
        raise BoundedExecutionError("command contains an invalid argument")
    process = subprocess.Popen(
        command,
        cwd=working_directory,
        env=dict(environment) if environment is not None else _bounded_environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if process.stdout is None or process.stderr is None:
        process.kill()
        raise BoundedExecutionError("failed to capture command output")
    stdout = bytearray()
    stderr = bytearray()
    lock = threading.Lock()
    exceeded = threading.Event()

    def drain(stream: BinaryIO, sink: bytearray) -> None:
        while chunk := stream.read(8192):
            with lock:
                remaining = max(0, output_limit_bytes - len(stdout) - len(stderr))
                sink.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    exceeded.set()
            if exceeded.is_set():
                process.kill()
                return

    readers = (
        threading.Thread(target=drain, args=(process.stdout, stdout), daemon=True),
        threading.Thread(target=drain, args=(process.stderr, stderr), daemon=True),
    )
    for reader in readers:
        reader.start()
    try:
        returncode = process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.wait()
        for reader in readers:
            reader.join()
        raise BoundedExecutionTimeout(
            f"command timed out after {timeout_seconds} seconds"
        ) from exc
    for reader in readers:
        reader.join()
    if exceeded.is_set():
        raise BoundedExecutionOutputLimit(
            f"command output exceeded {output_limit_bytes} bytes"
        )
    return subprocess.CompletedProcess(
        args=command,
        returncode=returncode,
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=stderr.decode("utf-8", errors="replace"),
    )


def _bounded_environment() -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in _PASSTHROUGH_ENVIRONMENT
    }
    environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        }
    )
    return environment
