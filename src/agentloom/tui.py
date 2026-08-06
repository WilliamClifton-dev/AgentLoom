"""Local Textual control panel for reproducible AgentLoom demo cases."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import ValidationError
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, DataTable, Input, Select, Static

from agentloom.contracts import (
    ApprovalDecisionRequest,
    ApprovalRecord,
    PatchArtifact,
    RiskReport,
    RootCauseReport,
    TaskCreate,
    TaskEventRecord,
    VerificationResult,
)
from agentloom.demo_case import DemoCase, DemoCaseError, load_demo_case
from agentloom.live_evidence import LiveEvidenceSummary
from agentloom.live_rollback import RollbackEvidenceSummary
from agentloom.mock_repair import MockRepairError, MockRepairRunner
from agentloom.storage import ApprovalVersionConflict, Database
from agentloom.workflow import RepairWorkflow


class DemoRunError(RuntimeError):
    """Raised when the TUI cannot list or execute a local demo case."""


class ApprovalQueueError(RuntimeError):
    """Raised when a local Human approval action cannot be recorded safely."""


@dataclass(frozen=True)
class DemoCaseSummary:
    case_id: str
    title: str
    issue: str
    runtime: str
    allowed_paths: tuple[str, ...]


@dataclass(frozen=True)
class RoleStatus:
    name: str
    state: str
    detail: str


@dataclass(frozen=True)
class DemoRunSummary:
    case: DemoCaseSummary
    task_id: str
    task_status: str
    verification_verdict: str
    risk_verdict: str
    root_cause: str
    patch_sha256: str | None
    artifacts_dir: Path
    events: tuple[TaskEventRecord, ...]
    roles: tuple[RoleStatus, ...]


class DemoRunService:
    """Read trusted local cases and expose deterministic results to the TUI."""

    def __init__(self, *, cases_root: Path, runs_root: Path) -> None:
        self._cases_root = cases_root.resolve()
        self._runs_root = runs_root.resolve()

    def list_cases(self) -> tuple[DemoCaseSummary, ...]:
        if not self._cases_root.is_dir():
            raise DemoRunError(f"demo cases directory is missing: {self._cases_root}")
        case_roots = sorted(
            path.parent for path in self._cases_root.glob("*/case.json") if path.is_file()
        )
        if not case_roots:
            raise DemoRunError("no demo cases were found")
        return tuple(_case_summary(_load_case(path)) for path in case_roots)

    def run_case(self, case_id: str) -> DemoRunSummary:
        cases = {case.case_id: case for case in self.list_cases()}
        if case_id not in cases:
            raise DemoRunError(f"unknown demo case: {case_id}")
        case_root = self._cases_root / case_id
        if not (case_root / "case.json").is_file():
            raise DemoRunError(f"demo case directory is missing: {case_id}")
        output_root = self._runs_root / case_id / uuid4().hex
        try:
            result = MockRepairRunner(case_root).run(output_root)
            root_cause = RootCauseReport.model_validate_json(
                (result.artifacts_dir / "root-cause-report.json").read_text(
                    encoding="utf-8"
                )
            )
            patch = PatchArtifact.model_validate_json(
                (result.artifacts_dir / "patch-artifact.json").read_text(
                    encoding="utf-8"
                )
            )
            verification = VerificationResult.model_validate_json(
                (result.artifacts_dir / "verification-result.json").read_text(
                    encoding="utf-8"
                )
            )
            risk = RiskReport.model_validate_json(
                (result.artifacts_dir / "risk-report.json").read_text(
                    encoding="utf-8"
                )
            )
            database = Database(f"sqlite:///{output_root / 'agentloom.db'}")
            events = tuple(database.list_task_events(result.task.task_id))
        except (DemoCaseError, MockRepairError, OSError, ValidationError) as exc:
            raise DemoRunError(str(exc)) from exc
        return DemoRunSummary(
            case=cases[case_id],
            task_id=result.task.task_id,
            task_status=result.task.status,
            verification_verdict=verification.verdict,
            risk_verdict=risk.verdict,
            root_cause=root_cause.summary,
            patch_sha256=patch.sha256,
            artifacts_dir=result.artifacts_dir,
            events=events,
            roles=(
                RoleStatus("Manager", result.task.status, "Task lifecycle finalized."),
                RoleStatus("Investigator", "COMPLETED", "Root-cause evidence recorded."),
                RoleStatus("Implementer", "COMPLETED", "Patch artifact issued."),
                RoleStatus("Verifier", verification.verdict, "Tests and risk checks completed."),
            ),
        )

    def run_failure_retry_demo(self) -> DemoRunSummary:
        """Run a deterministic verifier-failure, rollback, and retry branch."""
        case = next(
            (item for item in self.list_cases() if item.case_id == "pagination-boundary"),
            None,
        )
        if case is None:
            raise DemoRunError("pagination-boundary case is required for the retry demo")
        output_root = self._runs_root / "failure-retry" / uuid4().hex
        output_root.mkdir(parents=True, exist_ok=False)
        database = Database(f"sqlite:///{output_root / 'agentloom.db'}")
        database.create_schema()
        task = database.create_task(
            TaskCreate(
                title="Deterministic verifier failure and retry",
                repository_uri="fixture://failure-retry-demo",
                issue="The first workflow verification outcome is configured to fail.",
                acceptance_criteria=["ROLLED_BACK must be recorded before one retry."],
                allowed_paths=list(case.allowed_paths),
            )
        )
        workflow = RepairWorkflow(database)
        workflow.start(task.task_id)
        workflow.record_investigation(task.task_id, sufficient=True)
        workflow.record_implementation(task.task_id, requires_approval=False)
        workflow.record_verification(task.task_id, outcome="FAILED")
        workflow.rollback(task.task_id, retry=True)
        workflow.record_implementation(task.task_id, requires_approval=False)
        workflow.record_verification(task.task_id, outcome="PASSED")
        completed = workflow.finish(task.task_id, outcome="PASSED")
        events = tuple(database.list_task_events(task.task_id))
        evidence = {
            "schemaVersion": "agentloom.failure-retry-evidence/v1alpha1",
            "evidenceKind": "LOCAL_DETERMINISTIC_STATE_MACHINE",
            "taskId": task.task_id,
            "scenario": "verifier-failure-rollback-retry",
            "firstVerification": "FAILED",
            "rollbackStatus": "ROLLED_BACK",
            "retryAllowed": True,
            "retryCount": 1,
            "finalStatus": completed.status,
            "eventCount": len(events),
            "eventToStatuses": [event.to_status for event in events],
        }
        evidence_path = output_root / "failure-retry-evidence.json"
        evidence_path.write_text(
            json.dumps(evidence, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )
        return DemoRunSummary(
            case=case,
            task_id=completed.task_id,
            task_status=completed.status,
            verification_verdict="WORKFLOW_PASSED",
            risk_verdict="NOT_RUN",
            root_cause=(
                "The fixture recorded a failed workflow verification; a rollback "
                "transition preceded one retry."
            ),
            patch_sha256=None,
            artifacts_dir=output_root,
            events=events,
            roles=(
                RoleStatus("Manager", "COMPLETED", "Retry budget was consumed once."),
                RoleStatus("Investigator", "COMPLETED", "Evidence threshold remained valid."),
                RoleStatus("Implementer", "RETRIED", "Workflow re-entered implementation."),
                RoleStatus("Verifier", "WORKFLOW_PASSED", "Second fixture outcome passed."),
            ),
        )


class ApprovalQueueService:
    """Expose parameter-bound approvals to the local Human operator."""

    def __init__(self, database: Database, *, actor: str = "agentloom-developer") -> None:
        self._database = database
        self._actor = actor

    def list_approvals(self) -> tuple[ApprovalRecord, ...]:
        return tuple(self._database.list_approvals())

    def decide(
        self,
        approval_id: str,
        *,
        expected_version: int,
        status: Literal["APPROVED", "REJECTED"],
        reason: str,
    ) -> ApprovalRecord:
        if not reason.strip():
            raise ApprovalQueueError("A Human decision reason is required")
        try:
            approval = self._database.decide_approval(
                approval_id,
                ApprovalDecisionRequest(
                    expected_approval_version=expected_version,
                    status=status,
                    actor=self._actor,
                    reason=reason,
                ),
            )
        except ApprovalVersionConflict as exc:
            raise ApprovalQueueError("Approval is no longer pending") from exc
        if approval is None:
            raise ApprovalQueueError("Approval was not found")
        if approval.status == "EXPIRED":
            raise ApprovalQueueError("Approval expired before the Human decision")
        return approval


class AgentLoomApp(App[None]):
    """Compact dashboard for local demos and verified live evidence."""

    CSS = """
    /* AgentLoom visual tokens: deliberately flat, high-contrast operations palette. */
    $canvas: #0c1214;
    $surface: #121c1f;
    $surface-raised: #18272a;
    $border: #2b4549;
    $border-strong: #3c6865;
    $ink: #e7f1ee;
    $muted: #91a6a4;
    $primary: #62d7b9;
    $warning: #e7b66d;
    $danger: #ef8585;

    Screen {
        background: $canvas;
        color: $ink;
    }
    #titlebar {
        height: 3;
        padding: 1 2;
        background: $surface-raised;
        color: $ink;
        text-style: bold;
        border-bottom: solid $border-strong;
    }
    #main { height: 1fr; }
    #sidebar {
        width: 34;
        padding: 1 2;
        background: $surface;
        border-right: solid $border;
    }
    #workspace {
        width: 1fr;
        padding: 1 2;
        scrollbar-color: $border-strong;
        scrollbar-background: $canvas;
    }
    #case-details, #run-status, #artifact-details, #approval-details {
        padding: 1;
        background: $surface;
        border: solid $border;
    }
    #case-details {
        height: 10;
        color: $ink;
    }
    #run-status {
        height: 4;
        margin-top: 1;
        background: $surface-raised;
        color: $primary;
        text-style: bold;
        content-align: left middle;
    }
    #artifact-details {
        height: 8;
        margin-top: 1;
        color: $muted;
    }
    #agent-status {
        height: 10;
        margin-top: 1;
        background: $surface;
        border: solid $border;
    }
    #task-events {
        height: 1fr;
        min-height: 8;
        margin-top: 1;
        background: $surface;
        border: solid $border;
    }
    #approval-queue {
        height: 8;
        margin-top: 1;
        background: $surface;
        border: solid $border;
    }
    #approval-details {
        height: 12;
        margin-top: 1;
        color: $muted;
    }
    #approval-actions {
        height: 3;
        margin-top: 1;
    }
    #approval-reason {
        width: 1fr;
        border: solid $border;
    }
    #sidebar Button {
        width: 1fr;
        height: 3;
        margin-top: 1;
        border: none;
    }
    #approval-actions Button {
        width: auto;
        min-width: 12;
        margin-left: 1;
    }
    Button.-success { background: #1e6555; color: $ink; }
    Button.-warning { background: #76552b; color: $ink; }
    Button.-error { background: #743b42; color: $ink; }
    Select {
        width: 1fr;
        background: $surface-raised;
        border: solid $border;
    }
    .section-label {
        color: $primary;
        text-style: bold;
        margin-top: 1;
    }
    .section-label:first-child { margin-top: 0; }

    /* Applied by on_resize; Textual has no browser-style @media blocks. */
    #main.narrow { layout: vertical; }
    #main.narrow #sidebar {
        width: 1fr;
        height: 16;
        border-right: none;
        border-bottom: solid $border;
    }
    #main.narrow #workspace { width: 1fr; padding: 1; }
    #main.narrow #case-details { height: auto; min-height: 8; }
    #main.narrow #agent-status { height: 9; }
    #main.narrow #approval-queue { height: 7; }
    #main.narrow #approval-details { height: auto; min-height: 9; }
    #main.narrow #approval-actions { height: 6; layout: grid; grid-size: 2; }
    #main.narrow #approval-reason { column-span: 2; }
    """

    def __init__(
        self,
        service: DemoRunService,
        approval_service: ApprovalQueueService | None = None,
        live_summary: LiveEvidenceSummary | None = None,
        rollback_summary: RollbackEvidenceSummary | None = None,
        public_output: bool = False,
    ) -> None:
        super().__init__()
        self._service = service
        self._cases = service.list_cases()
        self._approval_service = approval_service
        self._approvals: tuple[ApprovalRecord, ...] = ()
        self._live_summary = live_summary
        self._rollback_summary = rollback_summary
        self._public_output = public_output
        if live_summary is not None and rollback_summary is not None:
            raise DemoRunError("live repair and rollback evidence are mutually exclusive")
        evidence_case_id = (
            live_summary.case_id
            if live_summary is not None
            else rollback_summary.case_id
            if rollback_summary is not None
            else None
        )
        if evidence_case_id is not None and not any(
            case.case_id == evidence_case_id for case in self._cases
        ):
            raise DemoRunError("live evidence does not match an available demo case")

    def compose(self) -> ComposeResult:
        options = [(case.title, case.case_id) for case in self._cases]
        title = "AgentLoom  |  Governed repair control plane"
        if self._live_summary is not None:
            title = "AgentLoom  |  Verified AgentTeams repair evidence"
        elif self._rollback_summary is not None:
            title = "AgentLoom  |  Verified AgentTeams rollback evidence"
        evidence_mode = self._live_summary is not None or self._rollback_summary is not None
        yield Static(title, id="titlebar")
        with Horizontal(id="main"):
            with Vertical(id="sidebar"):
                yield Static("DEMO CASE", classes="section-label")
                yield Select[str](
                    options,
                    value=(
                        self._live_summary.case_id
                        if self._live_summary is not None
                        else self._rollback_summary.case_id
                        if self._rollback_summary is not None
                        else self._cases[0].case_id
                    ),
                    allow_blank=False,
                    disabled=evidence_mode,
                    id="case-selector",
                )
                yield Button(
                    "Run selected case",
                    id="run-case",
                    variant="success",
                    disabled=evidence_mode,
                )
                yield Button(
                    "Run failure / retry",
                    id="run-failure-retry",
                    variant="warning",
                    disabled=evidence_mode,
                )
                yield Button(
                    "Refresh details",
                    id="refresh-case",
                    disabled=evidence_mode,
                )
                mode = "LOCAL MODE\nNo cloud model is called."
                if self._live_summary is not None:
                    mode = "LIVE EVIDENCE MODE\nNo model call is made by this viewer."
                elif self._rollback_summary is not None:
                    mode = "LIVE ROLLBACK EVIDENCE MODE\nNo model call is made by this viewer."
                yield Static(mode, id="run-status")
            with VerticalScroll(id="workspace"):
                yield Static("", id="case-details")
                yield Static("AGENT STATUS", classes="section-label")
                yield DataTable(id="agent-status", cursor_type="row")
                yield Static("TASK EVENTS", classes="section-label")
                yield DataTable(id="task-events", cursor_type="row")
                yield Static("", id="artifact-details")
                yield Static("APPROVAL QUEUE", classes="section-label")
                yield DataTable(id="approval-queue", cursor_type="row")
                yield Static("", id="approval-details")
                with Horizontal(id="approval-actions"):
                    yield Input(placeholder="Decision reason", id="approval-reason")
                    yield Button("Approve", id="approve-approval", variant="success")
                    yield Button("Reject", id="reject-approval", variant="error")
                yield Button("Refresh approvals", id="refresh-approvals")

    def on_mount(self) -> None:
        self.query_one("#agent-status", DataTable).add_columns("Agent", "State", "Output")
        self.query_one("#task-events", DataTable).add_columns("Order", "Evidence", "Detail")
        self.query_one("#approval-queue", DataTable).add_columns(
            "Status", "Risk", "Route", "Requested by", "Expires"
        )
        selected_case = (
            self._live_summary.case_id
            if self._live_summary is not None
            else self._rollback_summary.case_id
            if self._rollback_summary is not None
            else self._cases[0].case_id
        )
        self._show_case(selected_case)
        self._show_approval_queue()
        if self._live_summary is not None:
            self.show_live_summary(self._live_summary)
            return
        if self._rollback_summary is not None:
            self.show_rollback_summary(self._rollback_summary)
            return
        self._render_roles(
            (
                RoleStatus("Manager", "READY", "Awaiting a selected case."),
                RoleStatus("Investigator", "WAITING", "No investigation yet."),
                RoleStatus("Implementer", "WAITING", "No patch yet."),
                RoleStatus("Verifier", "WAITING", "No verification yet."),
            )
        )

    def on_select_changed(self, event: Select.Changed) -> None:
        if isinstance(event.value, str):
            self._show_case(event.value)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "approval-queue":
            self._show_approval_details(event.cursor_row)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "refresh-approvals":
            self._show_approval_queue()
            return
        if event.button.id in {"approve-approval", "reject-approval"}:
            self._decide_selected_approval(
                "APPROVED" if event.button.id == "approve-approval" else "REJECTED"
            )
            return
        if event.button.id == "run-failure-retry":
            self._show_retry_running()
            self.run_worker(
                self._run_failure_retry_in_worker,
                thread=True,
                exclusive=True,
                name="failure-retry-demo",
            )
            return
        selected = self.query_one("#case-selector", Select).value
        if not isinstance(selected, str):
            return
        if event.button.id == "refresh-case":
            self._show_case(selected)
        elif event.button.id == "run-case":
            self._show_running(selected)
            self.run_worker(
                lambda: self._run_case_in_worker(selected),
                thread=True,
                exclusive=True,
                name="mock-case-run",
            )

    def show_run_summary(self, summary: DemoRunSummary) -> None:
        self._render_roles(summary.roles)
        events = self.query_one("#task-events", DataTable)
        events.clear()
        for event in summary.events:
            events.add_row(
                str(event.plan_version),
                f"{event.from_status} -> {event.to_status}",
                event.reason,
            )
        self.query_one("#run-status", Static).update(
            Text(
                f"{summary.task_status}  |  verification {summary.verification_verdict}  |  "
                f"risk {summary.risk_verdict}"
            )
        )
        self.query_one("#artifact-details", Static).update(
            Text(
                "ARTIFACTS\n"
                f"Task: {summary.task_id}\n"
                f"Root cause: {summary.root_cause}\n"
                f"Patch SHA-256: {summary.patch_sha256 or 'N/A (state-machine demo)'}\n"
                f"Path: {self._display_path(summary.artifacts_dir)}"
            )
        )

    def show_live_summary(self, summary: LiveEvidenceSummary) -> None:
        role_details = {
            "agentloom-investigator": "Matrix event bound to root-cause evidence.",
            "agentloom-implementer": "Matrix event bound to the patch artifact.",
            "agentloom-verifier": "Matrix event bound to host verification.",
        }
        self._render_roles(
            (
                RoleStatus(
                    "Manager",
                    summary.manager_status,
                    "AgentTeams runtime health evidence passed.",
                ),
                *tuple(
                    RoleStatus(
                        event.agent_name.removeprefix("agentloom-").title(),
                        "TRACE_VERIFIED",
                        role_details[event.agent_name],
                    )
                    for event in summary.role_events
                ),
            )
        )
        events = self.query_one("#task-events", DataTable)
        events.clear()
        for order, event in enumerate(summary.role_events, start=1):
            events.add_row(
                str(order),
                event.agent_name.removeprefix("agentloom-").title(),
                event.event_id,
            )
        self.query_one("#run-status", Static).update(
            Text(f"LIVE VERIFIED  |  {summary.model}  |  hidden tests PASSED")
        )
        self.query_one("#artifact-details", Static).update(
            Text(
                "LIVE EVIDENCE\n"
                f"Task: {summary.task_id}\n"
                f"Case: {summary.case_id}  |  Provider: {summary.provider}\n"
                f"Model: {summary.model}\n"
                f"Hidden tests: {'PASSED' if summary.hidden_tests_passed else 'FAILED'}\n"
                f"Patch SHA-256: {summary.patch_sha256}\n"
                f"Path: {self._display_path(summary.artifacts_dir)}"
            )
        )

    def show_rollback_summary(self, summary: RollbackEvidenceSummary) -> None:
        role_details = {
            "VERIFICATION_FAILED": "Verifier failure event bound to the candidate snapshot.",
            "ROLLBACK_REQUESTED": "Manager rollback request bound to the failure.",
            "ROLLBACK_EXECUTED": "Implementer rollback event bound to host restoration.",
            "ROLLBACK_VERIFIED": "Verifier post-rollback event bound to passing checks.",
        }
        self._render_roles(
            (
                RoleStatus(
                    "Manager",
                    summary.manager_status,
                    "AgentTeams runtime health evidence passed.",
                ),
                *tuple(
                    RoleStatus(
                        event.agent_name.removeprefix("agentloom-").title(),
                        "TRACE_VERIFIED",
                        role_details[event.phase],
                    )
                    for event in summary.role_events
                    if event.phase != "ROLLBACK_REQUESTED"
                ),
            )
        )
        events = self.query_one("#task-events", DataTable)
        events.clear()
        for order, event in enumerate(summary.role_events, start=1):
            events.add_row(str(order), event.phase, event.event_id)
        self.query_one("#run-status", Static).update(
            Text(f"ROLLBACK VERIFIED  |  {summary.model}  |  snapshot restored")
        )
        self.query_one("#artifact-details", Static).update(
            Text(
                "LIVE ROLLBACK EVIDENCE\n"
                f"Task: {summary.task_id}\n"
                f"Case: {summary.case_id}  |  Provider: {summary.provider}\n"
                f"Model: {summary.model}\n"
                f"Failed patch SHA-256: {summary.failed_patch_sha256}\n"
                f"Failed snapshot SHA-256: {summary.failed_snapshot_sha256}\n"
                f"Approved snapshot SHA-256: {summary.approved_snapshot_sha256}\n"
                f"Path: {self._display_path(summary.artifacts_dir)}"
            )
        )

    def on_resize(self, event: object) -> None:
        """Switch to a stacked layout when the terminal cannot scan two columns."""
        size = getattr(event, "size", None)
        width = getattr(size, "width", 0)
        main = self.query_one("#main", Horizontal)
        if width < 100:
            main.add_class("narrow")
        else:
            main.remove_class("narrow")

    def _display_path(self, path: Path) -> str:
        return "<redacted>" if self._public_output else str(path)

    def _show_approval_queue(self) -> None:
        table = self.query_one("#approval-queue", DataTable)
        table.clear()
        if self._approval_service is None:
            self._approvals = ()
            self._show_approval_details(None)
            return
        self._approvals = self._approval_service.list_approvals()
        for approval in self._approvals:
            table.add_row(
                approval.status,
                approval.risk_level,
                approval.route_id,
                approval.requested_by,
                approval.expires_at.isoformat(timespec="seconds"),
                key=approval.approval_id,
            )
        self._show_approval_details(0 if self._approvals else None)

    def _show_approval_details(self, row_index: int | None) -> None:
        details = self.query_one("#approval-details", Static)
        if row_index is None or not (0 <= row_index < len(self._approvals)):
            details.update(Text("No pending or historical approvals."))
            self._set_decision_buttons(False)
            return
        approval = self._approvals[row_index]
        details.update(
            Text(
                "APPROVAL DETAIL\n"
                f"ID: {approval.approval_id}\n"
                f"Task: {approval.task_id}\n"
                f"Status: {approval.status}  |  Risk: {approval.risk_level}\n"
                f"Route: {approval.route_id}\n"
                f"Action: {approval.action_summary}\n"
                f"Parameter SHA-256: {approval.parameter_digest}\n"
                f"Rollback SHA-256: {approval.rollback_plan_hash}\n"
                f"Version: {approval.approval_version}  |  Requested by: {approval.requested_by}"
            )
        )
        self._set_decision_buttons(approval.status == "PENDING")

    def _set_decision_buttons(self, enabled: bool) -> None:
        self.query_one("#approve-approval", Button).disabled = not enabled
        self.query_one("#reject-approval", Button).disabled = not enabled

    def _decide_selected_approval(self, status: Literal["APPROVED", "REJECTED"]) -> None:
        if self._approval_service is None:
            self._show_approval_error("Approval service is not configured")
            return
        table = self.query_one("#approval-queue", DataTable)
        row_index = table.cursor_row
        if not (0 <= row_index < len(self._approvals)):
            self._show_approval_error("Select an approval first")
            return
        approval = self._approvals[row_index]
        reason = self.query_one("#approval-reason", Input).value
        try:
            self._approval_service.decide(
                approval.approval_id,
                expected_version=approval.approval_version,
                status=status,
                reason=reason,
            )
        except ApprovalQueueError as exc:
            self._show_approval_error(str(exc))
            return
        self.query_one("#run-status", Static).update(
            Text(f"APPROVAL {status}  |  {approval.approval_id}")
        )
        self._show_approval_queue()

    def _show_approval_error(self, message: str) -> None:
        self.query_one("#run-status", Static).update(
            Text(f"APPROVAL BLOCKED  |  {message}")
        )

    def _run_case_in_worker(self, case_id: str) -> None:
        try:
            summary = self._service.run_case(case_id)
        except DemoRunError as exc:
            self.call_from_thread(self._show_run_error, str(exc))
            return
        self.call_from_thread(self.show_run_summary, summary)

    def _run_failure_retry_in_worker(self) -> None:
        try:
            summary = self._service.run_failure_retry_demo()
        except DemoRunError as exc:
            self.call_from_thread(self._show_run_error, str(exc))
            return
        self.call_from_thread(self.show_run_summary, summary)

    def _show_case(self, case_id: str) -> None:
        case = next((item for item in self._cases if item.case_id == case_id), None)
        if case is None:
            return
        allowed = "\n".join(f"- {path}" for path in case.allowed_paths)
        self.query_one("#case-details", Static).update(
            Text(
                f"{case.title}\n\n"
                f"{case.issue}\n\n"
                f"Runtime: {case.runtime}\nAllowed paths:\n{allowed}"
            )
        )

    def _show_running(self, case_id: str) -> None:
        self.query_one("#run-status", Static).update(
            Text(f"RUNNING  |  validating and repairing {case_id}")
        )
        self._render_roles(
            (
                RoleStatus("Manager", "RUNNING", "Task lifecycle started."),
                RoleStatus("Investigator", "RUNNING", "Reproducing target failure."),
                RoleStatus("Implementer", "WAITING", "Awaiting investigation."),
                RoleStatus("Verifier", "WAITING", "Awaiting patch artifact."),
            )
        )

    def _show_retry_running(self) -> None:
        self.query_one("#run-status", Static).update(
            Text("RUNNING  |  failure -> rollback -> one retry")
        )
        self._render_roles(
            (
                RoleStatus("Manager", "RUNNING", "Retry budget is bounded to one attempt."),
                RoleStatus("Investigator", "COMPLETED", "Original failure evidence is retained."),
                RoleStatus("Implementer", "WAITING", "Awaiting bounded rollback transition."),
                RoleStatus("Verifier", "WAITING", "Awaiting the retry patch."),
            )
        )

    def _show_run_error(self, message: str) -> None:
        self.query_one("#run-status", Static).update(Text(f"FAILED  |  {message}"))
        self._render_roles(
            (
                RoleStatus("Manager", "FAILED", "Task did not complete."),
                RoleStatus("Investigator", "STOPPED", "No verified conclusion."),
                RoleStatus("Implementer", "STOPPED", "No approved patch."),
                RoleStatus("Verifier", "FAILED", "Verification did not pass."),
            )
        )

    def _render_roles(self, roles: tuple[RoleStatus, ...]) -> None:
        table = self.query_one("#agent-status", DataTable)
        table.clear()
        for role in roles:
            table.add_row(role.name, role.state, role.detail)


def _load_case(root: Path) -> DemoCase:
    try:
        case = load_demo_case(root)
    except (DemoCaseError, OSError, ValidationError) as exc:
        raise DemoRunError(f"invalid demo case at {root}: {exc}") from exc
    if case.manifest.case_id != case.root.name:
        raise DemoRunError("demo caseId must match its directory name")
    return case


def _case_summary(case: DemoCase) -> DemoCaseSummary:
    return DemoCaseSummary(
        case_id=case.manifest.case_id,
        title=case.manifest.title,
        issue=case.issue,
        runtime=f"{case.manifest.runtime.language} {case.manifest.runtime.version}",
        allowed_paths=tuple(case.manifest.allowed_changed_paths),
    )
