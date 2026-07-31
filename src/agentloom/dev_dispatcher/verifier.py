"""Allowlisted, shell-free acceptance command execution."""

import shlex
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

ProcessRunner = Callable[..., subprocess.CompletedProcess[str]]

ALLOWED_PREFIXES = (
    ("python", "-m", "pytest"),
    ("python", "-m", "ruff", "check"),
    ("python", "-m", "mypy"),
    ("git", "diff", "--check"),
    ("git", "status", "--short"),
)
SHELL_METACHARACTERS = frozenset(";&|><`\n\r")


def command_argv(command: str) -> list[str]:
    if any(character in command for character in SHELL_METACHARACTERS):
        raise ValueError("Acceptance command contains a shell metacharacter")
    argv = shlex.split(command, posix=True)
    if not any(tuple(argv[: len(prefix)]) == prefix for prefix in ALLOWED_PREFIXES):
        raise ValueError(f"Acceptance command is not allowed: {command}")
    return argv


class AcceptanceVerifier:
    def __init__(self, repository: Path, process_runner: ProcessRunner = subprocess.run) -> None:
        self.repository = repository.resolve()
        self._process_runner = process_runner

    def verify(self, commands: list[str]) -> tuple[bool, str]:
        summaries: list[str] = []
        for command in commands:
            argv = command_argv(command)
            if argv[0] == "python":
                argv[0] = sys.executable
            completed = self._process_runner(
                argv,
                cwd=self.repository,
                check=False,
                shell=False,
                text=True,
                capture_output=True,
                timeout=900,
            )
            output = (completed.stdout + completed.stderr)[-4000:]
            summaries.append(f"$ {command}\n{output}")
            if completed.returncode != 0:
                return False, "\n".join(summaries)
        return True, "\n".join(summaries)
