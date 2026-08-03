"""Operator commands for the local AgentLoom control plane."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from agentloom.tui import AgentLoomApp, DemoRunError, DemoRunService

app = typer.Typer(no_args_is_help=True, add_completion=False)

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CASES_ROOT = _ROOT / "demo" / "cases"
_DEFAULT_RUNS_ROOT = _ROOT / "artifacts" / "tui"


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
) -> None:
    """Launch the local Textual demo control panel."""
    try:
        AgentLoomApp(
            DemoRunService(cases_root=cases_root, runs_root=runs_root)
        ).run()
    except DemoRunError as exc:
        typer.echo(f"agentloom tui failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc


if __name__ == "__main__":
    app()
