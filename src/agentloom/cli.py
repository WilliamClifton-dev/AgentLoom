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
from agentloom.live_repair import LiveRepairError, LiveRepairVerifier
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


@app.callback()
def main() -> None:
    """AgentLoom operator commands."""


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
) -> None:
    """Launch the local Textual demo control panel."""
    try:
        approval_database.parent.mkdir(parents=True, exist_ok=True)
        database = Database(f"sqlite:///{approval_database.resolve()}")
        database.create_schema()
        AgentLoomApp(
            DemoRunService(cases_root=cases_root, runs_root=runs_root),
            approval_service=ApprovalQueueService(database),
        ).run()
    except (DemoRunError, OSError, SQLAlchemyError) as exc:
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
