from pathlib import Path

from agentloom.contracts import TaskCreate, TaskTransition
from agentloom.storage import Database


def test_transition_appends_reasoned_task_event(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'agentloom.db'}")
    database.create_schema()
    task = database.create_task(
        TaskCreate(
            title="Fix parser regression",
            repository_uri="fixture://buggy-python-service",
            issue="Parser returns None.",
            acceptance_criteria=["target test passes"],
            allowed_paths=["src/parser.py"],
        )
    )

    database.transition_task(
        task.task_id,
        TaskTransition(
            expected_plan_version=0,
            status="PLANNED",
            reason="Coordinator produced an evidence-bound plan.",
        ),
    )

    events = database.list_task_events(task.task_id)
    assert len(events) == 1
    assert events[0].from_status == "RECEIVED"
    assert events[0].to_status == "PLANNED"
    assert events[0].plan_version == 1
    assert events[0].reason == "Coordinator produced an evidence-bound plan."
