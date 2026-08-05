from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from textual.widgets import Button, DataTable, Input, Select, Static

from agentloom.contracts import ApprovalCreate, TaskCreate
from agentloom.live_evidence import EvidenceRoleEvent, LiveEvidenceSummary
from agentloom.live_rollback import RollbackEvidenceSummary, RollbackRoleEvent
from agentloom.storage import Database
from agentloom.tui import (
    AgentLoomApp,
    ApprovalQueueError,
    ApprovalQueueService,
    DemoRunError,
    DemoRunService,
)

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "demo" / "cases"


def make_approval_queue(tmp_path: Path) -> tuple[ApprovalQueueService, str]:
    database = Database(f"sqlite:///{tmp_path / 'approvals.db'}")
    database.create_schema()
    task = database.create_task(
        TaskCreate(
            title="Create reviewed pull request",
            repository_uri="fixture://approval-case",
            issue="A verified patch requires an external write.",
            acceptance_criteria=["Human approval matches the exact request."],
            allowed_paths=["lib/pagination.py"],
        )
    )
    approval = database.create_approval(
        ApprovalCreate(
            task_id=task.task_id,
            grant_id="grant-tui-01",
            parameter_digest="a" * 64,
            risk_level="L2",
            route_id="github-pr-v1",
            rollback_plan_hash="b" * 64,
            action_summary="Create a pull request from the verified patch.",
            requested_by="agentloom-implementer",
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )
    )
    return ApprovalQueueService(database), approval.approval_id


def test_demo_run_service_lists_manifest_defined_cases(tmp_path: Path) -> None:
    service = DemoRunService(cases_root=CASES, runs_root=tmp_path / "runs")

    cases = service.list_cases()

    assert [case.case_id for case in cases] == [
        "pagination-boundary",
        "severity-normalization",
    ]
    assert cases[0].runtime == "python >=3.12,<3.13"
    assert "extra page" in cases[0].issue


def test_demo_run_service_runs_selected_case_and_collects_evidence(
    tmp_path: Path,
) -> None:
    service = DemoRunService(cases_root=CASES, runs_root=tmp_path / "runs")

    summary = service.run_case("severity-normalization")

    assert summary.task_status == "COMPLETED"
    assert summary.verification_verdict == "PASSED"
    assert summary.risk_verdict == "PASSED"
    assert [role.name for role in summary.roles] == [
        "Manager",
        "Investigator",
        "Implementer",
        "Verifier",
    ]
    assert summary.roles[-1].state == "PASSED"
    assert summary.events[-1].to_status == "COMPLETED"
    assert (summary.artifacts_dir / "verification-result.json").is_file()


def test_demo_run_service_rejects_unknown_case_id(tmp_path: Path) -> None:
    service = DemoRunService(cases_root=CASES, runs_root=tmp_path / "runs")

    with pytest.raises(DemoRunError, match="unknown demo case"):
        service.run_case("../../not-a-case")


def test_demo_run_service_records_deterministic_failure_rollback_retry_evidence(
    tmp_path: Path,
) -> None:
    service = DemoRunService(cases_root=CASES, runs_root=tmp_path / "runs")

    summary = service.run_failure_retry_demo()

    transitions = [event.to_status for event in summary.events]
    assert summary.verification_verdict == "WORKFLOW_PASSED"
    assert summary.risk_verdict == "NOT_RUN"
    assert summary.patch_sha256 is None
    assert transitions.count("ROLLING_BACK") == 1
    assert transitions.count("ROLLED_BACK") == 1
    assert transitions[-1] == "COMPLETED"
    evidence = json.loads(
        (summary.artifacts_dir / "failure-retry-evidence.json").read_text(
            encoding="utf-8"
        )
    )
    assert evidence["evidenceKind"] == "LOCAL_DETERMINISTIC_STATE_MACHINE"
    assert evidence["firstVerification"] == "FAILED"
    assert evidence["retryAllowed"] is True
    assert evidence["finalStatus"] == "COMPLETED"


def test_demo_run_service_rejects_case_id_that_does_not_match_directory(
    tmp_path: Path,
) -> None:
    case_root = tmp_path / "cases" / "renamed-case"
    source = CASES / "severity-normalization"
    shutil.copytree(source, case_root)
    manifest_path = case_root / "case.json"
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8").replace(
            '"caseId": "severity-normalization"',
            '"caseId": "different-case-id"',
        ),
        encoding="utf-8",
    )

    service = DemoRunService(cases_root=case_root.parent, runs_root=tmp_path / "runs")

    with pytest.raises(DemoRunError, match="must match its directory name"):
        service.list_cases()


def test_approval_queue_service_records_one_version_bound_human_decision(
    tmp_path: Path,
) -> None:
    service, approval_id = make_approval_queue(tmp_path)
    pending = service.list_approvals()[0]

    approved = service.decide(
        approval_id,
        expected_version=pending.approval_version,
        status="APPROVED",
        reason="Exact request and rollback plan reviewed in the local TUI.",
    )

    assert approved.status == "APPROVED"
    assert approved.decided_by == "agentloom-developer"
    with pytest.raises(ApprovalQueueError, match="no longer pending"):
        service.decide(
            approval_id,
            expected_version=pending.approval_version,
            status="REJECTED",
            reason="A stale decision must not replace the approval.",
        )


@pytest.mark.asyncio
async def test_tui_renders_case_and_completed_evidence(tmp_path: Path) -> None:
    service = DemoRunService(cases_root=CASES, runs_root=tmp_path / "runs")
    summary = service.run_case("pagination-boundary")
    app = AgentLoomApp(service)

    async with app.run_test(size=(150, 44)):
        selector = app.query_one("#case-selector", Select)
        details = app.query_one("#case-details", Static)
        agents = app.query_one("#agent-status", DataTable)
        events = app.query_one("#task-events", DataTable)

        assert selector.value == "pagination-boundary"
        assert "extra page" in str(details.render())
        app._show_running("pagination-boundary")
        assert agents.get_row_at(1)[1] == "RUNNING"
        app.show_run_summary(summary)
        assert agents.row_count == 4
        assert events.row_count == len(summary.events)
        assert "PASSED" in str(app.query_one("#run-status", Static).render())


@pytest.mark.asyncio
async def test_tui_renders_bound_live_agentteams_evidence(tmp_path: Path) -> None:
    service = DemoRunService(cases_root=CASES, runs_root=tmp_path / "runs")
    role_events = tuple(
        EvidenceRoleEvent(
            agent_name=f"agentloom-{role}",
            matrix_user_id=f"@agentloom-{role}:example.test",
            room_id="!repair:example.test",
            event_id=f"${role}",
            origin_server_timestamp=1_700_000_000_000 + index,
        )
        for index, role in enumerate(
            ("investigator", "implementer", "verifier"), start=1
        )
    )
    live_summary = LiveEvidenceSummary(
        task_id="AL-LIVE-TUI-01",
        case_id="pagination-boundary",
        provider="dashscope",
        model="qwen3.7-plus",
        patch_sha256="a" * 64,
        manager_status="HEALTHY",
        role_events=role_events,
        hidden_tests_passed=True,
        artifacts_dir=tmp_path / "verified" / "artifacts",
    )
    app = AgentLoomApp(service, live_summary=live_summary)

    async with app.run_test(size=(150, 52)):
        agents = app.query_one("#agent-status", DataTable)
        events = app.query_one("#task-events", DataTable)

        assert app.query_one("#case-selector", Select).disabled
        assert app.query_one("#run-case", Button).disabled
        assert agents.row_count == 4
        assert agents.get_row_at(0)[1] == "HEALTHY"
        assert agents.get_row_at(3)[1] == "TRACE_VERIFIED"
        assert events.row_count == 3
        assert "LIVE VERIFIED" in str(app.query_one("#run-status", Static).render())
        artifact_text = str(app.query_one("#artifact-details", Static).render())
        assert "AL-LIVE-TUI-01" in artifact_text
        assert "Hidden tests: PASSED" in artifact_text


@pytest.mark.asyncio
async def test_tui_renders_bound_live_rollback_evidence(tmp_path: Path) -> None:
    service = DemoRunService(cases_root=CASES, runs_root=tmp_path / "runs")
    role_events = tuple(
        RollbackRoleEvent(
            phase=phase,
            agentName=agent,
            matrixUserId=f"@{local}:example.test",
            roomId="!repair:example.test",
            eventId=f"${local}-{index}",
            originServerTimestamp=1_700_000_000_000 + index,
            bindingSha256="d" * 64,
        )
        for index, (phase, agent, local) in enumerate(
            (
                ("VERIFICATION_FAILED", "agentloom-verifier", "agentloom-verifier"),
                ("ROLLBACK_REQUESTED", "agentloom-manager", "manager"),
                ("ROLLBACK_EXECUTED", "agentloom-implementer", "agentloom-implementer"),
                ("ROLLBACK_VERIFIED", "agentloom-verifier", "agentloom-verifier"),
            ),
            start=1,
        )
    )
    rollback_summary = RollbackEvidenceSummary(
        task_id="AL-LIVE-ROLLBACK-TUI-01",
        case_id="pagination-boundary",
        provider="dashscope",
        model="qwen3.7-plus",
        failed_patch_sha256="a" * 64,
        failed_snapshot_sha256="b" * 64,
        approved_snapshot_sha256="c" * 64,
        role_events=role_events,
        manager_status="HEALTHY",
        artifacts_dir=tmp_path / "rollback" / "artifacts",
    )
    app = AgentLoomApp(service, rollback_summary=rollback_summary)

    async with app.run_test(size=(150, 52)):
        agents = app.query_one("#agent-status", DataTable)
        events = app.query_one("#task-events", DataTable)

        assert app.query_one("#case-selector", Select).disabled
        assert agents.row_count == 4
        assert agents.get_row_at(0)[1] == "HEALTHY"
        assert agents.get_row_at(1)[1] == "TRACE_VERIFIED"
        assert events.row_count == 4
        assert "ROLLBACK VERIFIED" in str(app.query_one("#run-status", Static).render())
        artifact_text = str(app.query_one("#artifact-details", Static).render())
        assert "Approved snapshot SHA-256" in artifact_text


@pytest.mark.asyncio
async def test_tui_renders_and_decides_pending_approval(tmp_path: Path) -> None:
    demo_service = DemoRunService(cases_root=CASES, runs_root=tmp_path / "runs")
    approval_service, _ = make_approval_queue(tmp_path)
    app = AgentLoomApp(demo_service, approval_service=approval_service)

    async with app.run_test(size=(150, 80)) as pilot:
        queue = app.query_one("#approval-queue", DataTable)
        details = app.query_one("#approval-details", Static)
        reason = app.query_one("#approval-reason", Input)

        assert queue.row_count == 1
        assert "Create a pull request" in str(details.render())
        reason.value = "Exact L2 request and rollback plan reviewed."
        await pilot.click("#approve-approval")
        await pilot.pause()

        assert approval_service.list_approvals()[0].status == "APPROVED"
        assert "APPROVED" in str(details.render())


@pytest.mark.asyncio
async def test_tui_runs_failure_rollback_retry_demo_from_button(tmp_path: Path) -> None:
    service = DemoRunService(cases_root=CASES, runs_root=tmp_path / "runs")
    app = AgentLoomApp(service)

    async with app.run_test(size=(150, 60)) as pilot:
        app._show_retry_running()
        assert app.query_one("#agent-status", DataTable).get_row_at(1)[1] == "COMPLETED"
        await pilot.click("#run-failure-retry")
        for _ in range(20):
            await pilot.pause(0.05)
            status = str(app.query_one("#run-status", Static).render())
            if "verification WORKFLOW_PASSED" in status:
                break

        assert "verification WORKFLOW_PASSED" in status
        assert app.query_one("#task-events", DataTable).row_count == 10
        assert app.query_one("#agent-status", DataTable).get_row_at(2)[1] == "RETRIED"
