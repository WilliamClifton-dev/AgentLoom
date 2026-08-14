"""Operator commands for the local AgentLoom control plane."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy.exc import SQLAlchemyError

from agentloom.l2_approval import (
    L2ApprovalError,
    L2ApprovalVerifier,
    parse_l2_submission_json,
    prepare_l2_demo,
)
from agentloom.live_evidence import LiveEvidenceError, LiveEvidenceService
from agentloom.live_repair import LiveRepairError, LiveRepairVerifier
from agentloom.live_rollback import (
    LiveRollbackError,
    LiveRollbackVerifier,
    RollbackEvidenceService,
)
from agentloom.migration_rehearsal import MigrationRehearsal, MigrationRehearsalError
from agentloom.route_rehearsal import RouteRehearsalError, ToolRouteRollbackRehearsal
from agentloom.storage import Database
from agentloom.tui import (
    AgentLoomApp,
    ApprovalQueueService,
    DemoRunError,
    DemoRunService,
)

app = typer.Typer(no_args_is_help=True, add_completion=False)

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CASES_ROOT = _ROOT / "demo" / "cases"
_DEFAULT_RUNS_ROOT = _ROOT / "artifacts" / "tui"
_DEFAULT_APPROVAL_DATABASE = _DEFAULT_RUNS_ROOT / "control.db"
_DEFAULT_MIGRATION_REHEARSAL_ROOT = _ROOT / "artifacts" / "migrations" / "rehearsal"
_DEFAULT_ROUTE_REHEARSAL_ROOT = _ROOT / "artifacts" / "routes" / "rehearsal"


@app.callback()
def main() -> None:
    """AgentLoom operator commands."""


@app.command("rehearse-migration")
def rehearse_migration(
    output_root: Annotated[
        Path,
        typer.Option(help="Empty directory for synthetic migration evidence."),
    ] = _DEFAULT_MIGRATION_REHEARSAL_ROOT,
) -> None:
    """Rehearse SQLite upgrade, downgrade, and replay preservation."""
    try:
        result = MigrationRehearsal(_ROOT / "alembic.ini").run(output_root)
    except (MigrationRehearsalError, OSError) as exc:
        typer.echo(f"agentloom migration rehearsal failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        json.dumps(
            {
                "evidenceFile": "migration-rehearsal.json",
                "revisionCycle": result.revision_cycle,
                "status": result.status,
            },
            sort_keys=True,
        )
    )


@app.command("rehearse-route-rollback")
def rehearse_route_rollback(
    output_root: Annotated[
        Path,
        typer.Option(help="Empty directory for Tool route rollback evidence."),
    ] = _DEFAULT_ROUTE_REHEARSAL_ROOT,
) -> None:
    """Rehearse local-to-Docker Tool routing and configuration rollback."""
    try:
        result = ToolRouteRollbackRehearsal().run(output_root)
    except (RouteRehearsalError, OSError) as exc:
        typer.echo(f"agentloom route rehearsal failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        json.dumps(
            {
                "evidenceFile": "route-rollback-rehearsal.json",
                "providerSequence": result.provider_sequence,
                "status": result.status,
            },
            sort_keys=True,
        )
    )


@app.command()
def tui(
    cases_root: Annotated[
        Path,
        typer.Option(help="Directory containing strict AgentLoom demo cases."),
    ] = _DEFAULT_CASES_ROOT,
    runs_root: Annotated[
        Path,
        typer.Option(help="Directory for local, ignored demo-run artifacts."),
    ] = _DEFAULT_RUNS_ROOT,
    approval_database: Annotated[
        Path,
        typer.Option(help="SQLite database for the local Human approval queue."),
    ] = _DEFAULT_APPROVAL_DATABASE,
    health_evidence: Annotated[
        Path | None,
        typer.Option(help="Redacted AgentTeams deployment health evidence."),
    ] = None,
    run_evidence: Annotated[
        Path | None,
        typer.Option(help="Strict AgentTeams live repair run evidence."),
    ] = None,
    verified_evidence: Annotated[
        Path | None,
        typer.Option(help="Independent host verification evidence."),
    ] = None,
    rollback_evidence: Annotated[
        Path | None,
        typer.Option(help="Verified live rollback evidence."),
    ] = None,
    public_output: Annotated[
        bool,
        typer.Option(help="Redact local filesystem paths for public demos."),
    ] = False,
    auto_run: Annotated[
        bool,
        typer.Option(help="Run the first local case immediately after launch."),
    ] = False,
) -> None:
    """Launch the Textual panel for local or verified live evidence."""
    try:
        if rollback_evidence is not None and (
            run_evidence is not None or verified_evidence is not None
        ):
            raise LiveEvidenceError(
                "repair and rollback evidence modes are mutually exclusive"
            )
        live_paths = (health_evidence, run_evidence, verified_evidence)
        if rollback_evidence is None and any(path is not None for path in live_paths) and not all(
            path is not None for path in live_paths
        ):
            raise LiveEvidenceError(
                "health, run, and verified evidence must be provided together"
            )
        live_summary = None
        rollback_summary = None
        if all(path is not None for path in live_paths):
            assert health_evidence is not None
            assert run_evidence is not None
            assert verified_evidence is not None
            live_summary = LiveEvidenceService().load(
                health_path=health_evidence,
                run_path=run_evidence,
                verified_path=verified_evidence,
            )
        if rollback_evidence is not None:
            if health_evidence is None:
                raise LiveEvidenceError(
                    "rollback evidence requires deployment health evidence"
                )
            rollback_summary = RollbackEvidenceService().load(
                health_path=health_evidence,
                rollback_path=rollback_evidence,
            )
        approval_database.parent.mkdir(parents=True, exist_ok=True)
        database = Database(f"sqlite:///{approval_database.resolve()}")
        database.create_schema()
        AgentLoomApp(
            DemoRunService(cases_root=cases_root, runs_root=runs_root),
            approval_service=ApprovalQueueService(database),
            live_summary=live_summary,
            rollback_summary=rollback_summary,
            public_output=public_output,
            auto_run=auto_run,
        ).run()
    except (DemoRunError, LiveEvidenceError, OSError, SQLAlchemyError) as exc:
        typer.echo(f"agentloom tui failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command("verify-live")
def verify_live(
    submission: Annotated[
        Path,
        typer.Option(help="Strict JSON submission assembled from Matrix events."),
    ],
    case_root: Annotated[
        Path,
        typer.Option(help="Directory containing the frozen AgentLoom demo case."),
    ],
    output_root: Annotated[
        Path,
        typer.Option(help="Empty directory for verified repair artifacts."),
    ],
) -> None:
    """Verify one role-traced live AgentTeams repair submission."""
    try:
        result = LiveRepairVerifier(case_root).run(submission, output_root)
    except (LiveRepairError, OSError, ValueError, UnicodeError) as exc:
        typer.echo(f"agentloom live verification failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        json.dumps(
            {
                "taskId": result.task_id,
                "provider": result.provider,
                "model": result.model,
                "verificationVerdict": result.bundle.verification.verdict,
                "riskVerdict": result.bundle.risk.verdict,
                "patchSha256": result.bundle.patch.sha256,
                "artifactsDirectory": str(result.artifacts_dir),
            },
            indent=2,
            sort_keys=True,
        )
    )


@app.command("verify-rollback")
def verify_rollback(
    submission: Annotated[
        Path,
        typer.Option(help="Strict AgentTeams rollback submission assembled from Matrix events."),
    ],
    case_root: Annotated[
        Path,
        typer.Option(help="Directory containing the frozen AgentLoom demo case."),
    ],
    output_root: Annotated[
        Path,
        typer.Option(help="Empty directory for rollback verification artifacts."),
    ],
) -> None:
    """Verify and execute one role-traced live rollback."""
    try:
        result = LiveRollbackVerifier(case_root).run(submission, output_root)
    except (LiveRollbackError, OSError, ValueError, UnicodeError) as exc:
        typer.echo(f"agentloom rollback verification failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        json.dumps(
            {
                "schemaVersion": "agentloom.live-rollback-summary/v1alpha1",
                "status": "PASS",
                "taskId": result.task_id,
                "caseId": result.case_id,
                "provider": result.provider,
                "model": result.model,
                "failedPatchSha256": result.failed_patch_sha256,
                "failedSnapshotSha256": result.failed_snapshot_sha256,
                "approvedSnapshotSha256": result.approved_snapshot_sha256,
                "failureReproduced": result.failure_reproduced,
                "rollbackExecuted": result.rollback_executed,
                "postRollbackTestsPassed": result.post_rollback_tests_passed,
                "roleEventCount": len(result.role_event_ids),
                "artifactsDirectory": str(result.artifacts_dir.resolve()),
            },
            sort_keys=True,
        )
    )


@app.command("inspect-live")
def inspect_live(
    health_evidence: Annotated[
        Path,
        typer.Option(help="Redacted AgentTeams deployment health evidence."),
    ],
    run_evidence: Annotated[
        Path,
        typer.Option(help="Strict AgentTeams live repair run evidence."),
    ],
    verified_evidence: Annotated[
        Path,
        typer.Option(help="Independent host verification evidence."),
    ],
) -> None:
    """Validate and summarize one bound live AgentTeams evidence chain."""
    try:
        summary = LiveEvidenceService().load(
            health_path=health_evidence,
            run_path=run_evidence,
            verified_path=verified_evidence,
        )
    except LiveEvidenceError as exc:
        typer.echo(f"agentloom live evidence inspection failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        json.dumps(
            {
                "schemaVersion": "agentloom.live-evidence-summary/v1alpha1",
                "status": "PASS",
                "taskId": summary.task_id,
                "caseId": summary.case_id,
                "provider": summary.provider,
                "model": summary.model,
                "managerStatus": summary.manager_status,
                "roleEventCount": len(summary.role_events),
                "hiddenTestsPassed": summary.hidden_tests_passed,
                "patchSha256": summary.patch_sha256,
                "artifactsDirectory": str(summary.artifacts_dir.resolve()),
            },
            sort_keys=True,
        )
    )


@app.command("inspect-rollback")
def inspect_rollback(
    health_evidence: Annotated[
        Path,
        typer.Option(help="Redacted AgentTeams deployment health evidence."),
    ],
    rollback_evidence: Annotated[
        Path,
        typer.Option(help="Host-verified AgentTeams rollback evidence."),
    ],
    public_output: Annotated[
        bool,
        typer.Option(help="Redact local filesystem paths for public demos."),
    ] = False,
) -> None:
    """Validate one bound live AgentTeams rollback evidence chain."""
    try:
        summary = RollbackEvidenceService().load(
            health_path=health_evidence,
            rollback_path=rollback_evidence,
        )
    except LiveEvidenceError as exc:
        typer.echo(f"agentloom rollback evidence inspection failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        json.dumps(
            {
                "schemaVersion": "agentloom.live-rollback-summary/v1alpha1",
                "status": "PASS",
                "taskId": summary.task_id,
                "caseId": summary.case_id,
                "provider": summary.provider,
                "model": summary.model,
                "managerStatus": summary.manager_status,
                "roleEventCount": len(summary.role_events),
                "failedPatchSha256": summary.failed_patch_sha256,
                "failedSnapshotSha256": summary.failed_snapshot_sha256,
                "approvedSnapshotSha256": summary.approved_snapshot_sha256,
                "artifactsDirectory": (
                    "<redacted>"
                    if public_output
                    else str(summary.artifacts_dir.resolve())
                ),
            },
            sort_keys=True,
        )
    )


@app.command("prepare-l2")
def prepare_l2(
    database: Annotated[
        Path,
        typer.Option(help="SQLite database containing the local approval ledger."),
    ],
    output: Annotated[
        Path,
        typer.Option(help="Path for the strict, non-secret approval request JSON."),
    ],
    lifetime_minutes: Annotated[
        int,
        typer.Option(min=1, max=14, help="Short approval validity window."),
    ] = 10,
) -> None:
    """Create one short-lived L2 approval request without issuing a grant."""
    try:
        database.parent.mkdir(parents=True, exist_ok=True)
        output.parent.mkdir(parents=True, exist_ok=True)
        store = Database(f"sqlite:///{database.resolve()}")
        store.create_schema()
        preparation = prepare_l2_demo(store, lifetime_minutes=lifetime_minutes)
        output.write_text(
            preparation.model_dump_json(by_alias=True, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except (OSError, SQLAlchemyError, ValueError) as exc:
        typer.echo(f"agentloom L2 preparation failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        json.dumps(
            {
                "approvalId": preparation.request.approval_id,
                "taskId": preparation.request.task_id,
                "requestPath": str(output.resolve()),
                "status": "PENDING",
            },
            sort_keys=True,
        )
    )


@app.command("verify-l2")
def verify_l2(
    database: Annotated[
        Path,
        typer.Option(help="SQLite database containing the pending approval."),
    ],
    submission: Annotated[
        Path,
        typer.Option(help="Strict Manager request and Human decision event JSON."),
    ],
    evidence: Annotated[
        Path,
        typer.Option(help="Path for verified, redacted approval evidence."),
    ],
    room_id: Annotated[str, typer.Option(help="Expected AgentTeams Team Room ID.")],
    manager_user_id: Annotated[
        str,
        typer.Option(help="Expected AgentTeams Manager Matrix user ID."),
    ],
    human_user_id: Annotated[
        str,
        typer.Option(help="Expected AgentTeams Human Matrix user ID."),
    ],
) -> None:
    """Verify collected Manager and Human Matrix events and persist the decision."""
    try:
        store = Database(f"sqlite:///{database.resolve()}")
        collected = parse_l2_submission_json(submission.read_text(encoding="utf-8"))
        result = L2ApprovalVerifier(
            store,
            room_id=room_id,
            manager_user_id=manager_user_id,
            human_user_id=human_user_id,
        ).verify_submission(collected)
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(
            result.model_dump_json(by_alias=True, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except (L2ApprovalError, OSError, SQLAlchemyError, ValueError) as exc:
        typer.echo(f"agentloom L2 verification failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        json.dumps(
            {
                "approvalId": result.approval_id,
                "status": result.status,
                "evidencePath": str(evidence.resolve()),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    app()
