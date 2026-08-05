from __future__ import annotations

import difflib
import json
from pathlib import Path

import pytest

from agentloom.demo_case import snapshot_sha256
from agentloom.live_rollback import (
    LiveRollbackError,
    LiveRollbackVerifier,
    RollbackEvidenceService,
)

ROOT = Path(__file__).resolve().parents[1]
CASE_ROOT = ROOT / "demo" / "cases" / "pagination-boundary"
TASK_ID = "AL-LIVE-ROLLBACK-TEST-01"


def _failed_patch() -> str:
    approved = (CASE_ROOT / "expected" / "lib" / "pagination.py").read_text(
        encoding="utf-8"
    )
    failed = approved.replace(
        "return (total_items + page_size - 1) // page_size",
        "return total_items // page_size + 1",
    )
    return "".join(
        difflib.unified_diff(
            approved.splitlines(keepends=True),
            failed.splitlines(keepends=True),
            fromfile="a/lib/pagination.py",
            tofile="b/lib/pagination.py",
        )
    )


def _submission(path: Path) -> Path:
    failed_patch = _failed_patch()
    events = [
        (
            "VERIFICATION_FAILED",
            "agentloom-verifier",
            "@agentloom-verifier:example.test",
            "$verification-failed",
        ),
        (
            "ROLLBACK_REQUESTED",
            "agentloom-manager",
            "@manager:example.test",
            "$rollback-requested",
        ),
        (
            "ROLLBACK_EXECUTED",
            "agentloom-implementer",
            "@agentloom-implementer:example.test",
            "$rollback-executed",
        ),
        (
            "ROLLBACK_VERIFIED",
            "agentloom-verifier",
            "@agentloom-verifier:example.test",
            "$rollback-verified",
        ),
    ]
    payload = {
        "schemaVersion": "agentloom.live-rollback-submission/v1alpha1",
        "taskId": TASK_ID,
        "caseId": "pagination-boundary",
        "provider": "dashscope",
        "model": "qwen3.7-plus",
        "failedPatch": failed_patch,
        "failedPatchSha256": __import__("hashlib").sha256(
            failed_patch.encode("utf-8")
        ).hexdigest(),
        "rollbackPlan": {
            "strategy": "RESTORE_APPROVED_SNAPSHOT",
            "allowedChangedPaths": ["lib/pagination.py"],
            "reason": "Verifier rejected the candidate at an exact page boundary.",
        },
        "roleEvents": [
            {
                "phase": phase,
                "agentName": agent_name,
                "matrixUserId": matrix_user_id,
                "roomId": "!agentloom:example.test",
                "eventId": event_id,
                "originServerTimestamp": 1_700_000_000_000 + index,
            }
            for index, (phase, agent_name, matrix_user_id, event_id) in enumerate(
                events, start=1
            )
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _health(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "schemaVersion": "agentloom.deployment-health/v1alpha1",
                "checkedAt": "2026-08-05T05:27:59Z",
                "status": "PASS",
                "agentTeams": {
                    "tag": "v1.1.2",
                    "commit": "a99457830fafb99c991bdb666aa8a1eef2f83b12",
                },
                "failureCode": "",
                "checks": [
                    {"name": name, "passed": True, "detail": "verified"}
                    for name in (
                        "docker",
                        "controller",
                        "manager",
                        "team",
                        "workers",
                        "human",
                        "matrix-rooms",
                    )
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_live_rollback_reproduces_failure_and_restores_approved_snapshot(
    tmp_path: Path,
) -> None:
    result = LiveRollbackVerifier(CASE_ROOT).run(
        _submission(tmp_path / "submission.json"),
        tmp_path / "verified",
    )

    assert result.task_id == TASK_ID
    assert result.failure_reproduced
    assert result.rollback_executed
    assert result.post_rollback_tests_passed
    assert result.approved_snapshot_sha256 == snapshot_sha256(result.workspace)
    assert result.failed_snapshot_sha256 != result.approved_snapshot_sha256
    assert result.role_event_ids == (
        "$verification-failed",
        "$rollback-requested",
        "$rollback-executed",
        "$rollback-verified",
    )
    evidence = json.loads(
        (result.artifacts_dir / "live-rollback-evidence.json").read_text(
            encoding="utf-8"
        )
    )
    assert evidence["evidenceKind"] == "LIVE_AGENTTEAMS_HOST_VERIFIED_ROLLBACK"
    assert evidence["rollback"]["approvedSnapshotRestored"] is True


def test_live_rollback_rejects_out_of_order_or_wrong_role_events(tmp_path: Path) -> None:
    submission = _submission(tmp_path / "submission.json")
    payload = json.loads(submission.read_text(encoding="utf-8"))
    payload["roleEvents"][1]["agentName"] = "agentloom-implementer"
    submission.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(LiveRollbackError):
        LiveRollbackVerifier(CASE_ROOT).run(submission, tmp_path / "verified")


def test_live_rollback_rejects_failed_patch_hash_mismatch_without_echoing_content(
    tmp_path: Path,
) -> None:
    submission = _submission(tmp_path / "submission.json")
    payload = json.loads(submission.read_text(encoding="utf-8"))
    payload["failedPatch"] += "DO-NOT-ECHO-ROLLBACK-CONTENT"
    submission.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(LiveRollbackError) as captured:
        LiveRollbackVerifier(CASE_ROOT).run(submission, tmp_path / "verified")

    assert "DO-NOT-ECHO-ROLLBACK-CONTENT" not in str(captured.value)


def test_live_rollback_refuses_nonempty_output_directory(tmp_path: Path) -> None:
    output = tmp_path / "verified"
    output.mkdir()
    (output / "existing.txt").write_text("preserve", encoding="utf-8")

    with pytest.raises(LiveRollbackError, match="output directory must be empty"):
        LiveRollbackVerifier(CASE_ROOT).run(
            _submission(tmp_path / "submission.json"), output
        )

    assert (output / "existing.txt").read_text(encoding="utf-8") == "preserve"


def test_rollback_evidence_service_binds_deployment_health(tmp_path: Path) -> None:
    submission = _submission(tmp_path / "submission.json")
    result = LiveRollbackVerifier(CASE_ROOT).run(submission, tmp_path / "verified")
    evidence = result.artifacts_dir / "live-rollback-evidence.json"

    summary = RollbackEvidenceService().load(
        health_path=_health(tmp_path / "health.json"),
        rollback_path=evidence,
    )

    assert summary.task_id == TASK_ID
    assert summary.manager_status == "HEALTHY"
    assert summary.failed_snapshot_sha256 != summary.approved_snapshot_sha256
    assert [event.phase for event in summary.role_events] == [
        "VERIFICATION_FAILED",
        "ROLLBACK_REQUESTED",
        "ROLLBACK_EXECUTED",
        "ROLLBACK_VERIFIED",
    ]
