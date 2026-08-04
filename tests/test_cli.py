from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from click import unstyle
from typer.testing import CliRunner

from agentloom.cli import app
from agentloom.storage import Database


def test_tui_command_exposes_local_case_and_output_options() -> None:
    result = CliRunner().invoke(app, ["tui", "--help"])
    output = unstyle(result.output)

    assert result.exit_code == 0
    assert "Usage:" in output
    assert "Launch the local Textual demo control panel" in output
    assert "--cases-root" in output
    assert "--runs-root" in output
    assert "--approval-database" in output


def test_verify_live_command_exposes_submission_case_and_output_options() -> None:
    result = CliRunner().invoke(app, ["verify-live", "--help"])
    output = unstyle(result.output)

    assert result.exit_code == 0
    assert "Verify one role-traced live AgentTeams repair submission" in output
    assert "--submission" in output
    assert "--case-root" in output
    assert "--output-root" in output


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
