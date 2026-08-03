from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from textual.widgets import DataTable, Select, Static

from agentloom.tui import AgentLoomApp, DemoRunError, DemoRunService

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "demo" / "cases"


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
        app.show_run_summary(summary)
        assert agents.row_count == 4
        assert events.row_count == len(summary.events)
        assert "PASSED" in str(app.query_one("#run-status", Static).render())
