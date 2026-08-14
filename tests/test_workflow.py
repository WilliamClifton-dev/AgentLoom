from pathlib import Path

import pytest
from sqlalchemy import text

from agentloom.contracts import TaskCreate, WorkflowVerificationOutcome
from agentloom.storage import Database, TaskEventIntegrityError
from agentloom.workflow import RepairWorkflow


def make_workflow(tmp_path: Path) -> tuple[Database, RepairWorkflow, str]:
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
    return database, RepairWorkflow(database), task.task_id


def test_repair_workflow_completes_after_independent_verification(
    tmp_path: Path,
) -> None:
    database, workflow, task_id = make_workflow(tmp_path)

    assert workflow.start(task_id).status == "INVESTIGATING"
    assert workflow.record_investigation(task_id, sufficient=True).status == "IMPLEMENTING"
    assert workflow.record_implementation(task_id, requires_approval=False).status == "VERIFYING"
    assert workflow.record_verification(task_id, outcome="PASSED").status == "LEARNING"
    assert workflow.finish(task_id, outcome="PASSED").status == "COMPLETED"

    events = database.list_task_events(task_id)
    assert [event.to_status for event in events] == [
        "PLANNED",
        "INVESTIGATING",
        "IMPLEMENTING",
        "VERIFYING",
        "LEARNING",
        "COMPLETED",
    ]
    assert all(event.schema_version == "agentloom.task-event/v1alpha1" for event in events)
    assert all(event.event_type == "TASK_STATUS_TRANSITION" for event in events)
    assert all(event.correlation_id == task_id for event in events)
    assert all(event.has_valid_payload_digest() for event in events)
    assert events[0].causation_id is None
    assert [event.causation_id for event in events[1:]] == [
        event.event_id for event in events[:-1]
    ]


def test_repair_workflow_blocks_then_recovers_from_insufficient_evidence(
    tmp_path: Path,
) -> None:
    _, workflow, task_id = make_workflow(tmp_path)

    workflow.start(task_id)
    assert workflow.record_investigation(task_id, sufficient=False).status == "BLOCKED"
    assert workflow.resume_investigation(task_id).status == "INVESTIGATING"


def test_task_event_replay_rejects_tampered_payload(tmp_path: Path) -> None:
    database, workflow, task_id = make_workflow(tmp_path)
    workflow.start(task_id)

    with database.engine.begin() as connection:
        connection.execute(
            text("UPDATE task_events SET reason = :reason WHERE task_id = :task_id"),
            {"reason": "tampered", "task_id": task_id},
        )

    with pytest.raises(TaskEventIntegrityError, match="payload digest is invalid"):
        database.list_task_events(task_id)


def test_repair_workflow_cancels_after_approval_rejection(tmp_path: Path) -> None:
    _, workflow, task_id = make_workflow(tmp_path)

    workflow.start(task_id)
    workflow.record_investigation(task_id, sufficient=True)
    assert workflow.record_implementation(task_id, requires_approval=True).status == (
        "AWAITING_APPROVAL"
    )
    assert workflow.record_approval(task_id, approved=False).status == "LEARNING"
    assert workflow.finish(task_id, outcome="CANCELLED").status == "CANCELLED"


def test_repair_workflow_restarts_implementation_after_approval(tmp_path: Path) -> None:
    _, workflow, task_id = make_workflow(tmp_path)

    workflow.start(task_id)
    workflow.record_investigation(task_id, sufficient=True)
    workflow.record_implementation(task_id, requires_approval=True)
    assert workflow.record_approval(task_id, approved=True).status == "IMPLEMENTING"
    assert workflow.record_implementation(task_id, requires_approval=False).status == (
        "VERIFYING"
    )
def test_repair_workflow_rolls_back_failed_verification_before_failure(
    tmp_path: Path,
) -> None:
    database, workflow, task_id = make_workflow(tmp_path)

    workflow.start(task_id)
    workflow.record_investigation(task_id, sufficient=True)
    workflow.record_implementation(task_id, requires_approval=False)
    assert workflow.record_verification(task_id, outcome="FAILED").status == "ROLLING_BACK"
    assert workflow.rollback(task_id, retry=False).status == "LEARNING"
    assert workflow.finish(task_id, outcome="FAILED").status == "FAILED"

    assert [event.to_status for event in database.list_task_events(task_id)][-4:] == [
        "ROLLING_BACK",
        "ROLLED_BACK",
        "LEARNING",
        "FAILED",
    ]


def test_repair_workflow_retries_only_after_rollback(tmp_path: Path) -> None:
    _, workflow, task_id = make_workflow(tmp_path)

    workflow.start(task_id)
    workflow.record_investigation(task_id, sufficient=True)
    workflow.record_implementation(task_id, requires_approval=False)
    workflow.record_verification(task_id, outcome="FAILED")

    assert workflow.rollback(task_id, retry=True).status == "IMPLEMENTING"


@pytest.mark.parametrize("outcome", ["UNSAFE", "UNCERTAIN"])
def test_repair_workflow_rolls_back_non_passing_verdicts(
    tmp_path: Path, outcome: WorkflowVerificationOutcome
) -> None:
    _, workflow, task_id = make_workflow(tmp_path)

    workflow.start(task_id)
    workflow.record_investigation(task_id, sufficient=True)
    workflow.record_implementation(task_id, requires_approval=False)

    assert workflow.record_verification(task_id, outcome=outcome).status == "ROLLING_BACK"
