import json
from pathlib import Path

import pytest

from agentloom.live_evidence import LiveEvidenceError, LiveEvidenceService

TASK_ID = "AL-LIVE-PAGINATION-TEST-01"
SUBMISSION_SHA256 = "a" * 64
PATCH_SHA256 = "b" * 64


def write_evidence_set(root: Path) -> tuple[Path, Path, Path]:
    health_path = root / "health.json"
    run_path = root / "run.json"
    verified_path = root / "live-repair-evidence.json"
    role_events = [
        {
            "agentName": "agentloom-investigator",
            "matrixUserId": "@agentloom-investigator:example.test",
            "roomId": "!repair:example.test",
            "eventId": "$investigator",
            "originServerTimestamp": 1_700_000_000_001,
        },
        {
            "agentName": "agentloom-implementer",
            "matrixUserId": "@agentloom-implementer:example.test",
            "roomId": "!repair:example.test",
            "eventId": "$implementer",
            "originServerTimestamp": 1_700_000_000_002,
        },
        {
            "agentName": "agentloom-verifier",
            "matrixUserId": "@agentloom-verifier:example.test",
            "roomId": "!repair:example.test",
            "eventId": "$verifier",
            "originServerTimestamp": 1_700_000_000_003,
        },
    ]
    health_path.write_text(
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
    run_path.write_text(
        json.dumps(
            {
                "schemaVersion": "agentloom.live-repair-run/v1alpha1",
                "taskId": TASK_ID,
                "provider": "dashscope",
                "model": "qwen3.7-plus",
                "startedAt": "2026-08-04T11:40:00Z",
                "verifiedAt": "2026-08-04T11:46:00Z",
                "status": "SUBMISSION_READY",
                "strict": True,
                "criteria": {
                    "senderMustMatchRole": True,
                    "eventMustFollowTaskStart": True,
                    "markerMustBeIndependentTrimmedLine": True,
                    "resultObjectsMustFollowTaskStart": True,
                    "hiddenAndExpectedObjectsForbidden": True,
                    "resultObjectsMustBeAllowlisted": True,
                    "inputObjectsRemainUnchanged": True,
                    "completionEventMustFollowArtifacts": True,
                },
                "inputObjects": [],
                "roleEvents": [
                    {
                        "key": str(event["agentName"]).removeprefix("agentloom-"),
                        "agentName": event["agentName"],
                        "sender": event["matrixUserId"],
                        "eventId": event["eventId"],
                        "roomId": event["roomId"],
                        "originServerTimestamp": event["originServerTimestamp"],
                    }
                    for event in role_events
                ],
                "objects": [],
                "submissionSha256": SUBMISSION_SHA256,
            }
        ),
        encoding="utf-8",
    )
    verified_path.write_text(
        json.dumps(
            {
                "schemaVersion": "agentloom.live-repair-evidence/v1alpha1",
                "status": "PASS",
                "taskId": TASK_ID,
                "caseId": "pagination-boundary",
                "caseSnapshotSha256": "sha256:" + "d" * 64,
                "provider": "dashscope",
                "model": "qwen3.7-plus",
                "submissionSha256": SUBMISSION_SHA256,
                "patchSha256": PATCH_SHA256,
                "testResultsSha256": "e" * 64,
                "roleEvents": role_events,
                "independentVerification": {
                    "originalFailureReproduced": True,
                    "targetTestsPassed": True,
                    "regressionTestsPassed": True,
                    "hiddenTestsPassed": True,
                    "staticChecksPassed": True,
                    "unauthorizedChanges": False,
                },
            }
        ),
        encoding="utf-8",
    )
    return health_path, run_path, verified_path


def test_live_evidence_service_binds_runtime_run_and_host_verification(
    tmp_path: Path,
) -> None:
    health_path, run_path, verified_path = write_evidence_set(tmp_path)

    summary = LiveEvidenceService().load(
        health_path=health_path,
        run_path=run_path,
        verified_path=verified_path,
    )

    assert summary.task_id == TASK_ID
    assert summary.case_id == "pagination-boundary"
    assert summary.model == "qwen3.7-plus"
    assert summary.patch_sha256 == PATCH_SHA256
    assert summary.manager_status == "HEALTHY"
    assert [event.agent_name for event in summary.role_events] == [
        "agentloom-investigator",
        "agentloom-implementer",
        "agentloom-verifier",
    ]
    assert summary.hidden_tests_passed


def test_live_evidence_service_rejects_cross_file_event_mismatch(tmp_path: Path) -> None:
    health_path, run_path, verified_path = write_evidence_set(tmp_path)
    run = json.loads(run_path.read_text(encoding="utf-8"))
    run["roleEvents"][1]["eventId"] = "$different-event"
    run_path.write_text(json.dumps(run), encoding="utf-8")

    with pytest.raises(LiveEvidenceError, match="role events do not match"):
        LiveEvidenceService().load(
            health_path=health_path,
            run_path=run_path,
            verified_path=verified_path,
        )


def test_live_evidence_service_rejects_unapproved_provider_model_pair(
    tmp_path: Path,
) -> None:
    health_path, run_path, verified_path = write_evidence_set(tmp_path)
    run = json.loads(run_path.read_text(encoding="utf-8"))
    verified = json.loads(verified_path.read_text(encoding="utf-8"))
    run["provider"] = verified["provider"] = "deepseek"
    run_path.write_text(json.dumps(run), encoding="utf-8")
    verified_path.write_text(json.dumps(verified), encoding="utf-8")

    with pytest.raises(LiveEvidenceError, match="provider and model"):
        LiveEvidenceService().load(
            health_path=health_path,
            run_path=run_path,
            verified_path=verified_path,
        )


def test_live_evidence_service_rejects_secret_field_without_echoing_value(
    tmp_path: Path,
) -> None:
    health_path, run_path, verified_path = write_evidence_set(tmp_path)
    health = json.loads(health_path.read_text(encoding="utf-8"))
    health["initialPassword"] = "DO-NOT-ECHO-THIS-CREDENTIAL"
    health_path.write_text(json.dumps(health), encoding="utf-8")

    with pytest.raises(LiveEvidenceError) as captured:
        LiveEvidenceService().load(
            health_path=health_path,
            run_path=run_path,
            verified_path=verified_path,
        )

    assert "DO-NOT-ECHO-THIS-CREDENTIAL" not in str(captured.value)
