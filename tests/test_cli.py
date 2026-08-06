from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from click import unstyle
from typer.testing import CliRunner

from agentloom.cli import app
from agentloom.live_evidence import LiveEvidenceSummary
from agentloom.live_rollback import RollbackEvidenceSummary
from agentloom.storage import Database


def test_tui_command_exposes_local_case_and_output_options() -> None:
    result = CliRunner().invoke(app, ["tui", "--help"])
    output = unstyle(result.output)

    assert result.exit_code == 0
    assert "Usage:" in output
    assert "Launch the Textual panel for local or verified live evidence" in output
    assert "--cases-root" in output
    assert "--runs-root" in output
    assert "--approval-database" in output
    assert "--health-evidence" in output
    assert "--run-evidence" in output
    assert "--verified-evidence" in output
    assert "--rollback-evidence" in output
    assert "--public-output" in output
    assert "--auto-run" in output


def test_tui_requires_all_live_evidence_layers(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        ["tui", "--health-evidence", str(tmp_path / "health.json")],
    )

    assert result.exit_code == 1
    assert "must be provided together" in result.output


def test_verify_live_command_exposes_submission_case_and_output_options() -> None:
    result = CliRunner().invoke(app, ["verify-live", "--help"])
    output = unstyle(result.output)

    assert result.exit_code == 0
    assert "Verify one role-traced live AgentTeams repair submission" in output
    assert "--submission" in output
    assert "--case-root" in output
    assert "--output-root" in output


def test_verify_rollback_command_exposes_submission_case_and_output_options() -> None:
    result = CliRunner().invoke(app, ["verify-rollback", "--help"])
    output = unstyle(result.output)

    assert result.exit_code == 0
    assert "Verify and execute one role-traced live rollback" in output
    assert "--submission" in output
    assert "--case-root" in output
    assert "--output-root" in output


def test_verify_rollback_outputs_redacted_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class StubResult:
        task_id = "AL-LIVE-ROLLBACK-CLI-01"
        case_id = "pagination-boundary"
        provider = "dashscope"
        model = "qwen3.7-plus"
        failed_patch_sha256 = "a" * 64
        failed_snapshot_sha256 = "b" * 64
        approved_snapshot_sha256 = "c" * 64
        failure_reproduced = True
        rollback_executed = True
        post_rollback_tests_passed = True
        role_event_ids = ("$failed", "$requested", "$executed", "$verified")
        artifacts_dir = tmp_path / "artifacts"

    class StubVerifier:
        def __init__(self, case_root: Path) -> None:
            assert case_root == tmp_path / "case"

        def run(self, submission: Path, output_root: Path) -> StubResult:
            assert submission == tmp_path / "submission.json"
            assert output_root == tmp_path / "output"
            return StubResult()

    monkeypatch.setattr("agentloom.cli.LiveRollbackVerifier", StubVerifier)
    result = CliRunner().invoke(
        app,
        [
            "verify-rollback",
            "--submission",
            str(tmp_path / "submission.json"),
            "--case-root",
            str(tmp_path / "case"),
            "--output-root",
            str(tmp_path / "output"),
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "approvedSnapshotSha256": "c" * 64,
        "artifactsDirectory": str((tmp_path / "artifacts").resolve()),
        "caseId": "pagination-boundary",
        "failedPatchSha256": "a" * 64,
        "failedSnapshotSha256": "b" * 64,
        "failureReproduced": True,
        "model": "qwen3.7-plus",
        "postRollbackTestsPassed": True,
        "provider": "dashscope",
        "roleEventCount": 4,
        "rollbackExecuted": True,
        "schemaVersion": "agentloom.live-rollback-summary/v1alpha1",
        "status": "PASS",
        "taskId": "AL-LIVE-ROLLBACK-CLI-01",
    }


def test_inspect_rollback_command_exposes_health_and_evidence_options() -> None:
    result = CliRunner().invoke(app, ["inspect-rollback", "--help"])
    output = unstyle(result.output)

    assert result.exit_code == 0
    assert "Validate one bound live AgentTeams rollback evidence chain" in output
    assert "--health-evidence" in output
    assert "--rollback-evidence" in output
    assert "--public-output" in output


def test_inspect_rollback_public_output_redacts_local_artifact_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = RollbackEvidenceSummary(
        task_id="AL-LIVE-ROLLBACK-CLI-02",
        case_id="pagination-boundary",
        provider="stepfun",
        model="step-3.7-flash",
        failed_patch_sha256="a" * 64,
        failed_snapshot_sha256="b" * 64,
        approved_snapshot_sha256="c" * 64,
        role_events=(),
        manager_status="HEALTHY",
        artifacts_dir=tmp_path / "private" / "artifacts",
    )
    monkeypatch.setattr(
        "agentloom.cli.RollbackEvidenceService.load",
        lambda _self, **_paths: summary,
    )

    result = CliRunner().invoke(
        app,
        [
            "inspect-rollback",
            "--health-evidence",
            str(tmp_path / "health.json"),
            "--rollback-evidence",
            str(tmp_path / "rollback.json"),
            "--public-output",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["artifactsDirectory"] == "<redacted>"
    assert str(tmp_path) not in result.output

    default_result = CliRunner().invoke(
        app,
        [
            "inspect-rollback",
            "--health-evidence",
            str(tmp_path / "health.json"),
            "--rollback-evidence",
            str(tmp_path / "rollback.json"),
        ],
    )
    assert default_result.exit_code == 0
    assert json.loads(default_result.output)["artifactsDirectory"] == str(
        summary.artifacts_dir.resolve()
    )


def test_inspect_live_outputs_stable_redacted_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = LiveEvidenceSummary(
        task_id="AL-LIVE-CLI-01",
        case_id="pagination-boundary",
        provider="dashscope",
        model="qwen3.7-plus",
        patch_sha256="a" * 64,
        manager_status="HEALTHY",
        role_events=(),
        hidden_tests_passed=True,
        artifacts_dir=tmp_path / "artifacts",
    )
    monkeypatch.setattr(
        "agentloom.cli.LiveEvidenceService.load",
        lambda _self, **_paths: summary,
    )

    result = CliRunner().invoke(
        app,
        [
            "inspect-live",
            "--health-evidence",
            str(tmp_path / "health.json"),
            "--run-evidence",
            str(tmp_path / "run.json"),
            "--verified-evidence",
            str(tmp_path / "verified.json"),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload == {
        "artifactsDirectory": str(summary.artifacts_dir.resolve()),
        "caseId": "pagination-boundary",
        "hiddenTestsPassed": True,
        "managerStatus": "HEALTHY",
        "model": "qwen3.7-plus",
        "patchSha256": "a" * 64,
        "provider": "dashscope",
        "roleEventCount": 0,
        "schemaVersion": "agentloom.live-evidence-summary/v1alpha1",
        "status": "PASS",
        "taskId": "AL-LIVE-CLI-01",
    }


def test_l2_approval_commands_expose_separate_prepare_and_verify_phases() -> None:
    prepare = CliRunner().invoke(app, ["prepare-l2", "--help"])
    verify = CliRunner().invoke(app, ["verify-l2", "--help"])
    prepare_output = unstyle(prepare.output)
    verify_output = unstyle(verify.output)

    assert prepare.exit_code == 0
    assert "Create one short-lived L2 approval request" in prepare_output
    assert "--database" in prepare_output
    assert "--output" in prepare_output
    assert verify.exit_code == 0
    assert "Verify collected Manager and Human Matrix events" in verify_output
    assert "--submission" in verify_output
    assert "--evidence" in verify_output


def test_l2_cli_prepares_and_verifies_one_exact_human_decision(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "control.db"
    preparation_path = tmp_path / "preparation.json"
    submission_path = tmp_path / "submission.json"
    evidence_path = tmp_path / "evidence.json"
    runner = CliRunner()

    prepared = runner.invoke(
        app,
        [
            "prepare-l2",
            "--database",
            str(database_path),
            "--output",
            str(preparation_path),
        ],
    )
    assert prepared.exit_code == 0
    preparation = json.loads(preparation_path.read_text(encoding="utf-8"))
    request = preparation["request"]
    request_body = json.dumps(request, separators=(",", ":"))
    decision = {
        "schemaVersion": "agentloom.l2-approval-decision/v1alpha1",
        "approvalId": request["approvalId"],
        "approvalVersion": request["approvalVersion"],
        "taskId": request["taskId"],
        "grantId": request["grantId"],
        "parameterDigest": request["parameterDigest"],
        "riskLevel": "L2",
        "routeId": request["routeId"],
        "rollbackPlanHash": request["rollbackPlanHash"],
        "status": "APPROVED",
        "reason": "Exact request and rollback plan reviewed in Element.",
    }
    now = datetime.now(UTC)
    submission = {
        "schemaVersion": "agentloom.l2-approval-submission/v1alpha1",
        "requestEvent": {
            "roomId": "!team:matrix-local.hiclaw.io:18080",
            "eventId": "$request",
            "sender": "@manager:matrix-local.hiclaw.io:18080",
            "originServerTimestamp": int(
                (now - timedelta(seconds=2)).timestamp() * 1000
            ),
            "type": "m.room.message",
            "content": {"msgtype": "m.text", "body": request_body},
        },
        "decisionEvent": {
            "roomId": "!team:matrix-local.hiclaw.io:18080",
            "eventId": "$decision",
            "sender": "@agentloom-developer:matrix-local.hiclaw.io:18080",
            "originServerTimestamp": int(
                (now - timedelta(seconds=1)).timestamp() * 1000
            ),
            "type": "m.room.message",
            "content": {
                "msgtype": "m.text",
                "body": json.dumps(decision, separators=(",", ":")),
            },
        },
    }
    submission_path.write_text(json.dumps(submission), encoding="utf-8")

    verified = runner.invoke(
        app,
        [
            "verify-l2",
            "--database",
            str(database_path),
            "--submission",
            str(submission_path),
            "--evidence",
            str(evidence_path),
            "--room-id",
            "!team:matrix-local.hiclaw.io:18080",
            "--manager-user-id",
            "@manager:matrix-local.hiclaw.io:18080",
            "--human-user-id",
            "@agentloom-developer:matrix-local.hiclaw.io:18080",
        ],
    )

    assert verified.exit_code == 0
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["status"] == "APPROVED"
    stored = Database(f"sqlite:///{database_path}").get_approval(request["approvalId"])
    assert stored is not None
    assert stored.status == "APPROVED"


def test_verify_l2_does_not_echo_invalid_submission_values(tmp_path: Path) -> None:
    submission_path = tmp_path / "malformed.json"
    submission_path.write_text(
        json.dumps({"credential": "MATRIX-CREDENTIAL-DO-NOT-ECHO"}),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        [
            "verify-l2",
            "--database",
            str(tmp_path / "control.db"),
            "--submission",
            str(submission_path),
            "--evidence",
            str(tmp_path / "evidence.json"),
            "--room-id",
            "!team:matrix-local.hiclaw.io:18080",
            "--manager-user-id",
            "@manager:matrix-local.hiclaw.io:18080",
            "--human-user-id",
            "@agentloom-developer:matrix-local.hiclaw.io:18080",
        ],
    )

    assert result.exit_code == 1
    assert "MATRIX-CREDENTIAL-DO-NOT-ECHO" not in result.output
