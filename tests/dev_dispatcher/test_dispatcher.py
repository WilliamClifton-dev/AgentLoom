from pathlib import Path

import pytest

from agentloom.dev_dispatcher.dispatcher import (
    DevelopmentDispatcher,
    HumanActionRequired,
    build_task_prompt,
)
from agentloom.dev_dispatcher.models import DevelopmentTask
from agentloom.dev_dispatcher.verifier import command_argv


def task(**overrides: object) -> DevelopmentTask:
    values: dict[str, object] = {
        "id": "DEV-001",
        "title": "Implement MCP adapter",
        "objective": "Implement the internal MCP adapter and its tests.",
        "acceptance_commands": ["python -m pytest tests/test_policy_broker.py"],
    }
    values.update(overrides)
    return DevelopmentTask.model_validate(values)


def test_prompt_contains_architecture_task_git_state_and_limits(tmp_path: Path) -> None:
    architecture = tmp_path / "docs" / "architecture.md"
    architecture.parent.mkdir(parents=True)
    architecture.write_text("# Architecture\nFail closed.", encoding="utf-8")
    prompt = build_task_prompt(task(), architecture, " M existing.py", "1 baseline test passed")
    assert str(architecture) in prompt
    assert "DEV-001" in prompt
    assert "M existing.py" in prompt
    assert "1 baseline test passed" in prompt
    assert "Do not commit" in prompt
    assert "acceptance commands" in prompt
    assert "untrusted project data" in prompt


def test_human_boundary_blocks_external_action(tmp_path: Path) -> None:
    dispatcher = DevelopmentDispatcher.__new__(DevelopmentDispatcher)
    with pytest.raises(HumanActionRequired, match="publication"):
        dispatcher.ensure_automatable(task(risk_tags=["publication"]))


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("python -m pytest tests/test_policy_broker.py", ["python", "-m", "pytest"]),
        ("git diff --check", ["git", "diff", "--check"]),
    ],
)
def test_acceptance_command_allowlist(command: str, expected: list[str]) -> None:
    assert command_argv(command)[: len(expected)] == expected


@pytest.mark.parametrize(
    "command",
    [
        "python -m pytest; Remove-Item -Recurse .",
        "powershell -Command pytest",
        "git push origin main",
        "docker compose down",
    ],
)
def test_acceptance_command_rejects_shell_or_external_mutation(command: str) -> None:
    with pytest.raises(ValueError, match="not allowed|metacharacter"):
        command_argv(command)
