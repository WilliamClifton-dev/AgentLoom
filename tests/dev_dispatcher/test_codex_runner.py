from pathlib import Path

import pytest

from agentloom.dev_dispatcher.codex_runner import CodexRunner
from agentloom.dev_dispatcher.models import RouteDecision


def decision(**overrides: str) -> RouteDecision:
    values = {
        "model": "gpt-5.6-terra",
        "reasoning_effort": "medium",
        "reason": "Default engineering route.",
    }
    values.update(overrides)
    return RouteDecision.model_validate(values)


def test_builds_fixed_codex_argv_without_shell_interpolation(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    runner = CodexRunner(tmp_path)
    argv = runner.build_argv(decision(), "Implement task; Remove-Item must remain plain text")
    assert argv[:2] == ["codex", "exec"]
    assert argv[argv.index("-C") + 1] == str(tmp_path.resolve())
    assert "--dangerously-bypass-approvals-and-sandbox" not in argv
    assert argv[-1] == "Implement task; Remove-Item must remain plain text"


def test_rejects_workspace_outside_git_repository(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Git repository"):
        CodexRunner(tmp_path)


def test_route_decision_rejects_unapproved_model() -> None:
    with pytest.raises(ValueError):
        decision(model="unknown-model")
