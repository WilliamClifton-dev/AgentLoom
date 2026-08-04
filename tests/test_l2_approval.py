from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from agentloom.contracts import ApprovalCreate, TaskCreate
from agentloom.l2_approval import (
    L2ApprovalError,
    L2ApprovalVerifier,
    prepare_l2_demo,
)
from agentloom.storage import Database

ROOM_ID = "!agentloom-team:matrix-local.hiclaw.io:18080"
MANAGER_ID = "@manager:matrix-local.hiclaw.io:18080"
HUMAN_ID = "@agentloom-developer:matrix-local.hiclaw.io:18080"


def make_pending(database: Database, now: datetime) -> tuple[str, datetime]:
    task = database.create_task(
        TaskCreate(
            title="Create reviewed pull request",
            repository_uri="fixture://approval-case",
            issue="A verified patch is ready for an external write.",
            acceptance_criteria=["Human approval is bound to the exact request."],
            allowed_paths=["src/parser.py"],
        )
    )
    expires_at = now + timedelta(minutes=10)
    approval = database.create_approval(
        ApprovalCreate(
            task_id=task.task_id,
            grant_id="grant-01",
            parameter_digest="a" * 64,
            risk_level="L2",
            route_id="github-pr-v1",
            rollback_plan_hash="b" * 64,
            action_summary="Create a pull request from the verified patch.",
            requested_by="agentloom-implementer",
            expires_at=expires_at,
        )
    )
    return approval.approval_id, expires_at


def matrix_event(
    *,
    event_id: str,
    sender: str,
    timestamp: datetime,
    body: str,
    room_id: str = ROOM_ID,
) -> dict[str, Any]:
    return {
        "roomId": room_id,
        "eventId": event_id,
        "sender": sender,
        "originServerTimestamp": int(timestamp.timestamp() * 1000),
        "type": "m.room.message",
        "content": {"msgtype": "m.text", "body": body},
    }


def request_body(approval_id: str, expires_at: datetime) -> str:
    return (
        "{"
        '"schemaVersion":"agentloom.l2-approval-request/v1alpha1",'
        f'"approvalId":"{approval_id}",'
        '"approvalVersion":0,'
        '"taskId":"task-bound-at-runtime",'
        '"grantId":"grant-01",'
        f'"parameterDigest":"{"a" * 64}",'
        '"riskLevel":"L2",'
        '"routeId":"github-pr-v1",'
        f'"rollbackPlanHash":"{"b" * 64}",'
        '"actionSummary":"Create a pull request from the verified patch.",'
        f'"expiresAt":"{expires_at.isoformat()}",'
        '"transportOrigin":"deterministic-host"'
        "}"
    )


def decision_body(
    approval_id: str,
    *,
    status: str = "APPROVED",
    reason: str = "Exact request and rollback plan reviewed.",
) -> str:
    return (
        "{"
        '"schemaVersion":"agentloom.l2-approval-decision/v1alpha1",'
        f'"approvalId":"{approval_id}",'
        '"approvalVersion":0,'
        '"taskId":"task-bound-at-runtime",'
        '"grantId":"grant-01",'
        f'"parameterDigest":"{"a" * 64}",'
        '"riskLevel":"L2",'
        '"routeId":"github-pr-v1",'
        f'"rollbackPlanHash":"{"b" * 64}",'
        f'"status":"{status}",'
        f'"reason":"{reason}"'
        "}"
    )


def setup_verifier(
    tmp_path: Path,
    now: datetime,
) -> tuple[Database, L2ApprovalVerifier, dict[str, Any], dict[str, Any], str]:
    database = Database(f"sqlite:///{tmp_path / 'agentloom.db'}")
    database.create_schema()
    approval_id, expires_at = make_pending(database, now)
    pending = database.get_approval(approval_id)
    assert pending is not None

    request = request_body(approval_id, expires_at).replace(
        "task-bound-at-runtime", pending.task_id
    )
    decision = decision_body(approval_id).replace(
        "task-bound-at-runtime", pending.task_id
    )
    request_event = matrix_event(
        event_id="$request",
        sender=MANAGER_ID,
        timestamp=now - timedelta(seconds=10),
        body=request,
    )
    decision_event = matrix_event(
        event_id="$decision",
        sender=HUMAN_ID,
        timestamp=now - timedelta(seconds=5),
        body=decision,
    )
    verifier = L2ApprovalVerifier(
        database,
        room_id=ROOM_ID,
        manager_user_id=MANAGER_ID,
        human_user_id=HUMAN_ID,
        clock=lambda: now,
    )
    return database, verifier, request_event, decision_event, approval_id


@pytest.mark.parametrize("status", ["APPROVED", "REJECTED"])
def test_exact_human_decision_updates_pending_approval(
    tmp_path: Path,
    status: str,
) -> None:
    now = datetime.now(UTC)
    database, verifier, request_event, decision_event, approval_id = setup_verifier(
        tmp_path, now
    )
    pending = database.get_approval(approval_id)
    assert pending is not None
    decision_event["content"]["body"] = decision_body(
        approval_id,
        status=status,
    ).replace("task-bound-at-runtime", pending.task_id)

    evidence = verifier.verify(request_event, decision_event)

    updated = database.get_approval(approval_id)
    assert updated is not None
    assert updated.status == status
    assert updated.approval_version == 1
    assert updated.decided_by == HUMAN_ID
    assert evidence.status == status
    assert evidence.request_event.event_id == "$request"
    assert evidence.decision_event.event_id == "$decision"
    serialized = evidence.model_dump_json(by_alias=True)
    assert "access_token" not in serialized
    assert "password" not in serialized
    assert "signature" not in serialized


Mutation = Callable[[dict[str, Any], dict[str, Any]], None]


def mutate_request_sender(request: dict[str, Any], _: dict[str, Any]) -> None:
    request["sender"] = "@forged:matrix-local.hiclaw.io:18080"


def mutate_human_sender(_: dict[str, Any], decision: dict[str, Any]) -> None:
    decision["sender"] = "@forged:matrix-local.hiclaw.io:18080"


def mutate_room(_: dict[str, Any], decision: dict[str, Any]) -> None:
    decision["roomId"] = "!other:matrix-local.hiclaw.io:18080"


def mutate_stale_request(request: dict[str, Any], _: dict[str, Any]) -> None:
    request["originServerTimestamp"] -= 16 * 60 * 1000


def mutate_reordered_events(request: dict[str, Any], decision: dict[str, Any]) -> None:
    decision["originServerTimestamp"] = request["originServerTimestamp"]


def mutate_version(_: dict[str, Any], decision: dict[str, Any]) -> None:
    decision["content"]["body"] = decision["content"]["body"].replace(
        '"approvalVersion":0', '"approvalVersion":1'
    )


def mutate_digest(_: dict[str, Any], decision: dict[str, Any]) -> None:
    decision["content"]["body"] = decision["content"]["body"].replace(
        "a" * 64, "c" * 64
    )


def mutate_rollback(_: dict[str, Any], decision: dict[str, Any]) -> None:
    decision["content"]["body"] = decision["content"]["body"].replace(
        "b" * 64, "d" * 64
    )


def mutate_padded_route(_: dict[str, Any], decision: dict[str, Any]) -> None:
    decision["content"]["body"] = decision["content"]["body"].replace(
        '"routeId":"github-pr-v1"', '"routeId":" github-pr-v1 "'
    )


def mutate_message_type(_: dict[str, Any], decision: dict[str, Any]) -> None:
    decision["content"]["msgtype"] = "m.notice"


@pytest.mark.parametrize(
    "mutation",
    [
        mutate_request_sender,
        mutate_human_sender,
        mutate_room,
        mutate_stale_request,
        mutate_reordered_events,
        mutate_version,
        mutate_digest,
        mutate_rollback,
        mutate_padded_route,
        mutate_message_type,
    ],
    ids=lambda mutation: mutation.__name__,
)
def test_untrusted_matrix_mismatch_fails_without_database_change(
    tmp_path: Path,
    mutation: Mutation,
) -> None:
    now = datetime.now(UTC)
    database, verifier, request_event, decision_event, approval_id = setup_verifier(
        tmp_path, now
    )
    mutation(request_event, decision_event)

    with pytest.raises(L2ApprovalError):
        verifier.verify(request_event, decision_event)

    unchanged = database.get_approval(approval_id)
    assert unchanged is not None
    assert unchanged.status == "PENDING"
    assert unchanged.approval_version == 0


def test_malformed_or_oversized_body_fails_without_database_change(
    tmp_path: Path,
) -> None:
    now = datetime.now(UTC)
    database, verifier, request_event, decision_event, approval_id = setup_verifier(
        tmp_path, now
    )
    decision_event["content"]["body"] = "{" + ("x" * 16_384)

    with pytest.raises(L2ApprovalError):
        verifier.verify(request_event, decision_event)

    unchanged = database.get_approval(approval_id)
    assert unchanged is not None
    assert unchanged.status == "PENDING"


def test_replayed_event_cannot_overwrite_existing_decision(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    database, verifier, request_event, decision_event, approval_id = setup_verifier(
        tmp_path, now
    )
    verifier.verify(request_event, decision_event)
    pending = database.get_approval(approval_id)
    assert pending is not None
    decision_event["content"]["body"] = decision_body(
        approval_id,
        status="REJECTED",
        reason="Replay must not replace the original decision.",
    ).replace("task-bound-at-runtime", pending.task_id)

    with pytest.raises(L2ApprovalError):
        verifier.verify(request_event, decision_event)

    unchanged = database.get_approval(approval_id)
    assert unchanged is not None
    assert unchanged.status == "APPROVED"
    assert unchanged.approval_version == 1


def test_prepare_l2_demo_creates_parameter_bound_pending_request(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'agentloom.db'}")
    database.create_schema()

    preparation = prepare_l2_demo(database)

    request = preparation.request
    pending = database.get_approval(request.approval_id)
    assert pending is not None
    assert pending.status == "PENDING"
    assert pending.task_id == request.task_id
    assert pending.grant_id == request.grant_id
    assert pending.parameter_digest == request.parameter_digest
    assert pending.rollback_plan_hash == request.rollback_plan_hash
    assert request.transport_origin == "deterministic-host"
    assert request.risk_level == "L2"
