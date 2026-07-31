"""Safe, bounded Codex subprocess adapter."""

import subprocess
from collections.abc import Callable
from pathlib import Path

from agentloom.dev_dispatcher.models import ExecutionResult, RouteDecision

ProcessRunner = Callable[..., subprocess.CompletedProcess[str]]


class CodexRunner:
    def __init__(self, repository: Path, process_runner: ProcessRunner = subprocess.run) -> None:
        self.repository = repository.resolve()
        if not self._is_git_repository():
            raise ValueError(f"Workspace is not a Git repository: {self.repository}")
        self._process_runner = process_runner

    def build_argv(
        self, decision: RouteDecision, prompt: str, output_file: Path | None = None
    ) -> list[str]:
        argv = [
            "codex",
            "exec",
            "-m",
            decision.model,
            "-c",
            f"model_reasoning_effort={decision.reasoning_effort}",
            "-C",
            str(self.repository),
            "--sandbox",
            "workspace-write",
        ]
        if output_file is not None:
            argv.extend(["-o", str(output_file.resolve())])
        argv.append(prompt)
        return argv

    def run(self, decision: RouteDecision, prompt: str, output_file: Path) -> ExecutionResult:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.unlink(missing_ok=True)
        completed = self._process_runner(
            self.build_argv(decision, prompt, output_file),
            cwd=self.repository,
            check=False,
            shell=False,
            text=True,
            capture_output=True,
            timeout=3600,
        )
        final_message = output_file.read_text(encoding="utf-8") if output_file.exists() else ""
        if not final_message:
            final_message = completed.stderr[-20_000:]
        return ExecutionResult(
            return_code=completed.returncode,
            final_message=final_message,
            output_file=str(output_file.resolve()),
        )

    def _is_git_repository(self) -> bool:
        current = self.repository
        return any((candidate / ".git").exists() for candidate in (current, *current.parents))
