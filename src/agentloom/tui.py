"""Local Textual control panel for reproducible AgentLoom demo cases."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, DataTable, Select, Static

from agentloom.contracts import (
    PatchArtifact,
    RiskReport,
    RootCauseReport,
    TaskEventRecord,
    VerificationResult,
)
from agentloom.demo_case import DemoCase, DemoCaseError, load_demo_case
from agentloom.mock_repair import MockRepairError, MockRepairRunner
from agentloom.storage import Database


class DemoRunError(RuntimeError):
    """Raised when the TUI cannot list or execute a local demo case."""


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
    patch_sha256: str
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


class AgentLoomApp(App[None]):
    """Compact local dashboard for a deterministic repair demonstration."""

    CSS = """
    Screen { background: #101716; color: #e6efeb; }
    #titlebar { height: 3; padding: 1 2; background: #173b36; color: #ffffff; }
    #main { height: 1fr; }
    #sidebar { width: 34; padding: 1; border-right: solid #46645d; }
    #workspace { width: 1fr; padding: 1; }
    #case-details, #run-status, #artifact-details { padding: 1; border: solid #46645d; }
    #case-details { height: 10; }
    #run-status { height: 3; margin-top: 1; }
    #artifact-details { height: 8; margin-top: 1; }
    #agent-status { height: 10; margin-top: 1; }
    #task-events { height: 1fr; margin-top: 1; }
    Button { width: 1fr; margin-top: 1; }
    Select { width: 1fr; }
    .section-label { color: #91cdbf; margin-top: 1; }
    """

    def __init__(self, service: DemoRunService) -> None:
        super().__init__()
        self._service = service
        self._cases = service.list_cases()

    def compose(self) -> ComposeResult:
        options = [(case.title, case.case_id) for case in self._cases]
        yield Static("AgentLoom  |  Governed repair control plane", id="titlebar")
        with Horizontal(id="main"):
            with Vertical(id="sidebar"):
                yield Static("DEMO CASE", classes="section-label")
                yield Select[str](
                    options,
                    value=self._cases[0].case_id,
                    allow_blank=False,
                    id="case-selector",
                )
                yield Button("Run selected case", id="run-case", variant="success")
                yield Button("Refresh details", id="refresh-case")
                yield Static("LOCAL MODE\nNo cloud model is called.", id="run-status")
            with VerticalScroll(id="workspace"):
                yield Static("", id="case-details")
                yield Static("AGENT STATUS", classes="section-label")
                yield DataTable(id="agent-status", cursor_type="row")
                yield Static("TASK EVENTS", classes="section-label")
                yield DataTable(id="task-events", cursor_type="row")
                yield Static("", id="artifact-details")

    def on_mount(self) -> None:
        self.query_one("#agent-status", DataTable).add_columns("Agent", "State", "Output")
        self.query_one("#task-events", DataTable).add_columns(
            "Version", "Transition", "Reason"
        )
        self._show_case(self._cases[0].case_id)
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

    def on_button_pressed(self, event: Button.Pressed) -> None:
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
                f"Patch SHA-256: {summary.patch_sha256}\n"
                f"Path: {summary.artifacts_dir}"
            )
        )

    def _run_case_in_worker(self, case_id: str) -> None:
        try:
            summary = self._service.run_case(case_id)
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
