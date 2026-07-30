from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_initial_migration_upgrades_and_downgrades(tmp_path: Path) -> None:
    database_path = tmp_path / "migration.db"
    database_url = f"sqlite:///{database_path}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "head")

    engine = create_engine(database_url)
    assert "tasks" in inspect(engine).get_table_names()
    assert "task_events" in inspect(engine).get_table_names()
    task_columns = {column["name"] for column in inspect(engine).get_columns("tasks")}
    assert "plan_version" in task_columns

    command.downgrade(config, "base")

    assert "tasks" not in inspect(engine).get_table_names()
