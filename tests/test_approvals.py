from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agentloom.contracts import ApprovalCreate, ApprovalDecisionRequest, TaskCreate
from agentloom.storage import ApprovalTaskNotFound, ApprovalVersionConflict, Database


def make_task(database: Database) -> str:
    return database.create_task(
        TaskCreate(
            title="Create reviewed pull request",
            repository_uri="fixture://approval-case",
            issue="A reviewed patch is ready for an external write.",
            acceptance_criteria=["Approval is bound to the exact request."],
            allowed_paths=["src/parser.py"],
        )
    ).task_id


def make_approval(task_id: str) -> ApprovalCreate:
    return ApprovalCreate(
        task_id=task_id,
        grant_id="grant-01",
        parameter_digest="a" * 64,
        risk_level="L2",
        route_id="github-pr-v1",
        rollback_plan_hash="b" * 64,
        action_summary="Create a pull request from the verified patch.",
        requested_by="agentloom-implementer",
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )


def test_database_approves_exact_pending_request_once(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'agentloom.db'}")
    database.create_schema()
    pending = database.create_approval(make_approval(make_task(database)))

    approved = database.decide_approval(
        pending.approval_id,
        ApprovalDecisionRequest(
            expected_approval_version=0,
            status="APPROVED",
            actor="agentloom-developer",
            reason="Rollback plan and exact request hash reviewed.",
        ),
    )

    assert approved is not None
    assert approved.status == "APPROVED"
    assert approved.approval_version == 1
    assert approved.decision_reason == "Rollback plan and exact request hash reviewed."


def test_database_rejects_stale_approval_decision(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'agentloom.db'}")
    database.create_schema()
    pending = database.create_approval(make_approval(make_task(database)))
    database.decide_approval(
        pending.approval_id,
        ApprovalDecisionRequest(
            expected_approval_version=0,
            status="REJECTED",
            actor="agentloom-developer",
            reason="External write is not approved for this demo.",
        ),
    )

    with pytest.raises(ApprovalVersionConflict):
        database.decide_approval(
            pending.approval_id,
            ApprovalDecisionRequest(
                expected_approval_version=0,
                status="APPROVED",
                actor="agentloom-developer",
                reason="Stale approval must not overwrite the rejection.",
            ),
        )


def test_database_does_not_persist_an_overlong_approval(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'agentloom.db'}")
    database.create_schema()
    request = make_approval(make_task(database)).model_copy(
        update={"expires_at": datetime.now(UTC) + timedelta(minutes=16)}
    )

    with pytest.raises(ValueError, match="approval lifetime cannot exceed 15 minutes"):
        database.create_approval(request)


def test_database_rejects_approval_for_an_unknown_task(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'agentloom.db'}")
    database.create_schema()

    with pytest.raises(ApprovalTaskNotFound):
        database.create_approval(make_approval("task-missing"))


def test_database_lists_approvals_newest_first_and_filters_status(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite:///{tmp_path / 'agentloom.db'}")
    database.create_schema()
    task_id = make_task(database)
    rejected = database.create_approval(make_approval(task_id))
    database.decide_approval(
        rejected.approval_id,
        ApprovalDecisionRequest(
            expected_approval_version=0,
            status="REJECTED",
            actor="agentloom-developer",
            reason="External write is outside the demo boundary.",
        ),
    )
    pending = database.create_approval(
        make_approval(task_id).model_copy(
            update={"grant_id": "grant-02", "parameter_digest": "c" * 64}
        )
    )

    approvals = database.list_approvals()

    assert [item.approval_id for item in approvals] == [
        pending.approval_id,
        rejected.approval_id,
    ]
    assert database.list_approvals(status="PENDING") == [pending]
    assert database.list_approvals(status="REJECTED")[0].approval_id == (
        rejected.approval_id
    )
