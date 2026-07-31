"""Minimal CLI for automatic development task dispatch."""

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from agentloom.dev_dispatcher.dispatcher import DevelopmentDispatcher, HumanActionRequired

app = typer.Typer(no_args_is_help=True, help="Run bounded AgentLoom development tasks.")
console = Console()


def dispatcher(repository: Path) -> DevelopmentDispatcher:
    return DevelopmentDispatcher(repository)


@app.command()
def plan(
    repository: Annotated[
        Path,
        typer.Option("--repository", "-C", exists=True, file_okay=False, resolve_path=True),
    ] = Path("."),
) -> None:
    """Show the next task and selected model without changing the repository."""
    try:
        task, decision = dispatcher(repository).plan()
    except (LookupError, HumanActionRequired) as error:
        console.print(f"[yellow]{error}[/yellow]")
        raise typer.Exit(code=2) from error
    console.print(f"[bold]{task.id}[/bold] {task.title}")
    console.print(f"Model: {decision.model} / {decision.reasoning_effort}")
    console.print(f"Reason: {decision.reason}")


@app.command()
def status(
    repository: Annotated[
        Path,
        typer.Option("--repository", "-C", exists=True, file_okay=False, resolve_path=True),
    ] = Path("."),
) -> None:
    """Display the development task ledger."""
    development_dispatcher = dispatcher(repository)
    backlog = development_dispatcher.backlog.load()
    table = Table("Task", "Status", "Attempts", "Model", "Title")
    for task in backlog.tasks:
        table.add_row(
            task.id,
            task.status,
            str(task.attempts),
            task.selected_model or "-",
            task.title,
        )
    console.print(table)


@app.command()
def start(
    repository: Annotated[
        Path,
        typer.Option("--repository", "-C", exists=True, file_okay=False, resolve_path=True),
    ] = Path("."),
    max_tasks: Annotated[int, typer.Option(min=1, max=3)] = 1,
) -> None:
    """Execute up to three ready tasks, stopping on the first failure."""
    development_dispatcher = dispatcher(repository)
    for _ in range(max_tasks):
        try:
            task, decision, passed, evidence = development_dispatcher.run_one()
        except LookupError:
            console.print("[green]No ready development tasks.[/green]")
            return
        except HumanActionRequired as error:
            console.print(f"[yellow]{error}[/yellow]")
            raise typer.Exit(code=2) from error
        console.print(
            f"{task.id}: {decision.model}/{decision.reasoning_effort} -> "
            f"{'passed' if passed else 'failed'}"
        )
        if not passed:
            console.print(evidence[-2000:])
            raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
