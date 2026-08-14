# SQLite migration rehearsal specification

## Objective

Provide one deterministic, model-free command that proves a legacy AgentLoom
SQLite database can upgrade to the current Alembic head, downgrade to the legacy
revision without losing legacy rows, upgrade again with valid replay metadata,
and finally downgrade to base.

## Commands

- Focused tests: `.venv\Scripts\python -m pytest tests/test_migration_rehearsal.py tests/test_migrations.py`
- CLI rehearsal: `.venv\Scripts\agentloom rehearse-migration --output-root <empty-directory>`
- Quality: `.venv\Scripts\ruff check .` and `.venv\Scripts\mypy src tests`

## Project structure

- `src/agentloom/migration_rehearsal.py`: orchestration and evidence contract.
- `src/agentloom/cli.py`: thin operator command.
- `tests/test_migration_rehearsal.py`: real Alembic/SQLite integration tests.
- `artifacts/migrations/`: ignored default evidence output.

## Behavior and style

The service receives an explicit empty output directory, owns only the database
and JSON evidence beneath it, and uses Alembic public commands. It creates one
strict legacy Task and TaskEvent at revision `0003`, then executes:

```text
0003 -> head -> 0003 -> head -> base
```

At each relevant step it records revision, expected tables, row counts, and
stable semantic digests. Evidence is JSON with camelCase boundary fields and no
absolute host path, credential, raw Grant, or model content.

## Testing strategy

- RED first: the service/CLI does not yet exist.
- Integration test uses a real temporary SQLite database and real Alembic
  migrations, asserts legacy row preservation and valid replay digest after both
  upgrades, and asserts business tables are absent at base.
- Failure tests reject non-empty output directories and unexpected revision or
  data drift fail closed.

## Boundaries

- Always use Python 3.12, SQLite, current repository Alembic scripts, and
  deterministic synthetic data.
- Never mutate `agentloom.db`, a user-provided existing database, deployment
  configuration, or external service.
- Never call a model or Docker for this task.
- Route switching and rollback are explicitly Task 22, not inferred from this
  database-only rehearsal.

## Success criteria

- The exact revision cycle completes and evidence reports `PASS`.
- Legacy Task/Event semantic digests are identical before and after both head
  upgrades; replay payload digests validate.
- Downgrade to `0003` preserves legacy rows and removes 0004-0006 structures.
- Downgrade to base removes AgentLoom business tables.
- Focused and full repository gates pass.
