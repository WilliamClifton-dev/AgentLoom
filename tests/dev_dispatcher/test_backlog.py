import json
from pathlib import Path

import pytest

from agentloom.dev_dispatcher.backlog import BacklogStore
from agentloom.dev_dispatcher.models import DevelopmentBacklog, DevelopmentTask


def make_backlog() -> DevelopmentBacklog:
    return DevelopmentBacklog(
        tasks=[
            DevelopmentTask(
                id="TASK-002",
                title="Second",
                objective="Depends on first.",
                dependencies=["TASK-001"],
                acceptance_commands=["python -m pytest"],
            ),
            DevelopmentTask(
                id="TASK-001",
                title="First",
                objective="Ready now.",
                acceptance_commands=["python -m pytest"],
            ),
        ]
    )


def test_selects_first_ready_task_by_priority(tmp_path: Path) -> None:
    store = BacklogStore(tmp_path / "backlog.json")
    store.save(make_backlog())
    assert store.next_ready().id == "TASK-001"


def test_completed_dependency_unlocks_task(tmp_path: Path) -> None:
    store = BacklogStore(tmp_path / "backlog.json")
    store.save(make_backlog())
    store.transition("TASK-001", "completed")
    assert store.next_ready().id == "TASK-002"


def test_save_is_valid_json_and_leaves_no_temp_file(tmp_path: Path) -> None:
    path = tmp_path / "backlog.json"
    store = BacklogStore(path)
    store.save(make_backlog())
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 1
    assert not list(tmp_path.glob("*.tmp"))


def test_rejects_unknown_dependency(tmp_path: Path) -> None:
    backlog = make_backlog()
    backlog.tasks[0] = backlog.tasks[0].model_copy(update={"dependencies": ["missing"]})
    with pytest.raises(ValueError, match="unknown dependency"):
        BacklogStore(tmp_path / "backlog.json").save(backlog)


def test_recovers_interrupted_running_task(tmp_path: Path) -> None:
    store = BacklogStore(tmp_path / "backlog.json")
    store.save(make_backlog())
    store.transition("TASK-001", "running")
    recovered = store.recover_interrupted()
    assert recovered == ["TASK-001"]
    task = store.next_ready()
    assert task.id == "TASK-001"
    assert task.status == "failed"
    assert task.attempts == 1
