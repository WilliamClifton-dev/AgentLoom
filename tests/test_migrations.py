from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from agentloom.storage import Database


def test_initial_migration_upgrades_and_downgrades(tmp_path: Path) -> None:
    database_path = tmp_path / "migration.db"
    database_url = f"sqlite:///{database_path}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "head")

    engine = create_engine(database_url)
    assert "tasks" in inspect(engine).get_table_names()
    assert "task_events" in inspect(engine).get_table_names()
    assert "tool_calls" in inspect(engine).get_table_names()
    assert "consumed_grant_nonces" in inspect(engine).get_table_names()
    assert "approvals" in inspect(engine).get_table_names()
    task_columns = {column["name"] for column in inspect(engine).get_columns("tasks")}
    assert "plan_version" in task_columns
    event_columns = {column["name"] for column in inspect(engine).get_columns("task_events")}
    assert {
        "schema_version",
        "event_type",
        "actor",
        "causation_id",
        "correlation_id",
        "payload_digest",
    }.issubset(event_columns)

    command.downgrade(config, "base")

    assert "tasks" not in inspect(engine).get_table_names()
    assert "approvals" not in inspect(engine).get_table_names()


def test_task_event_metadata_migration_backfills_existing_events(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy.db"
    database_url = f"sqlite:///{database_path}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "0003")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO tasks "
                "(task_id, title, repository_uri, issue, acceptance_criteria, "
                "allowed_paths, status, plan_version, created_at) "
                "VALUES (:task_id, :title, :repository_uri, :issue, :acceptance, "
                ":allowed, :status, :plan_version, :created_at)"
            ),
            {
                "task_id": "task-legacy",
                "title": "Legacy task",
                "repository_uri": "fixture://legacy",
                "issue": "legacy issue",
                "acceptance": '["test"]',
                "allowed": '["src/**"]',
                "status": "PLANNED",
                "plan_version": 1,
                "created_at": "2026-08-14 00:00:00",
            },
        )
        connection.execute(
            text(
                "INSERT INTO task_events "
                "(event_id, task_id, from_status, to_status, plan_version, reason, created_at) "
                "VALUES (:event_id, :task_id, :from_status, :to_status, :plan_version, "
                ":reason, :created_at)"
            ),
            {
                "event_id": "event-legacy",
                "task_id": "task-legacy",
                "from_status": "RECEIVED",
                "to_status": "PLANNED",
                "plan_version": 1,
                "reason": "legacy transition",
                "created_at": "2026-08-14 00:00:01",
            },
        )

    command.upgrade(config, "head")
    events = Database(database_url).list_task_events("task-legacy")

    assert len(events) == 1
    assert events[0].causation_id is None
    assert events[0].correlation_id == "task-legacy"
    assert events[0].has_valid_payload_digest()
