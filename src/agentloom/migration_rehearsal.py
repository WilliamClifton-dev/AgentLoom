"""Deterministic SQLite migration rehearsal with redacted evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from pydantic import Field
from sqlalchemy import Engine, create_engine, inspect, text

from agentloom.contracts import ContractModel
from agentloom.storage import Database

_APPLICATION_TABLES = {
    "approvals",
    "consumed_grant_nonces",
    "task_events",
    "tasks",
    "tool_calls",
}
_TASK_ID = "task-migration-rehearsal"
_EVENT_ID = "event-migration-rehearsal"


class MigrationRehearsalError(Exception):
    """Raised when a migration rehearsal cannot prove the required invariants."""


class MigrationStep(ContractModel):
    name: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    tables: list[str]
    task_count: int = Field(alias="taskCount", ge=0)
    event_count: int = Field(alias="eventCount", ge=0)


class MigrationRehearsalResult(ContractModel):
    schema_version: Literal["agentloom.migration-rehearsal/v1alpha1"] = Field(
        default="agentloom.migration-rehearsal/v1alpha1",
        alias="schemaVersion",
    )
    status: Literal["PASS"] = "PASS"
    revision_cycle: list[str] = Field(alias="revisionCycle", min_length=5, max_length=5)
    legacy_task_digest: str = Field(alias="legacyTaskDigest", pattern=r"^[a-f0-9]{64}$")
    legacy_event_digest: str = Field(alias="legacyEventDigest", pattern=r"^[a-f0-9]{64}$")
    first_upgrade_payload_digest: str = Field(
        alias="firstUpgradePayloadDigest", pattern=r"^[a-f0-9]{64}$"
    )
    second_upgrade_payload_digest: str = Field(
        alias="secondUpgradePayloadDigest", pattern=r"^[a-f0-9]{64}$"
    )
    semantic_digests_stable: bool = Field(alias="semanticDigestsStable")
    replay_digests_valid: bool = Field(alias="replayDigestsValid")
    steps: list[MigrationStep] = Field(min_length=5, max_length=5)


class MigrationRehearsal:
    """Run the current migrations through an owned synthetic SQLite database."""

    def __init__(self, alembic_config: Path) -> None:
        self._alembic_config = alembic_config.resolve()

    def run(self, output_root: Path) -> MigrationRehearsalResult:
        if output_root.is_symlink():
            raise MigrationRehearsalError("output root must be an empty directory")
        root = output_root.resolve()
        self._prepare_empty_output(root)
        database_path = root / "rehearsal.db"
        database_url = f"sqlite:///{database_path.as_posix()}"
        config = self._config(database_url)
        engine = create_engine(database_url)

        try:
            command.upgrade(config, "0003")
            self._assert_revision(engine, "0003")
            self._seed_legacy_rows(engine)
            legacy_task_digest, legacy_event_digest = self._legacy_digests(engine)
            steps = [self._step(engine, "legacy-seed")]

            command.upgrade(config, "head")
            self._assert_revision(engine, "0006")
            first_event_digest = self._validated_event_digest(database_url)
            self._assert_legacy_digests(engine, legacy_task_digest, legacy_event_digest)
            steps.append(self._step(engine, "first-head-upgrade"))

            command.downgrade(config, "0003")
            self._assert_revision(engine, "0003")
            self._assert_legacy_digests(engine, legacy_task_digest, legacy_event_digest)
            self._assert_legacy_schema(engine)
            steps.append(self._step(engine, "legacy-rollback"))

            command.upgrade(config, "head")
            self._assert_revision(engine, "0006")
            second_event_digest = self._validated_event_digest(database_url)
            self._assert_legacy_digests(engine, legacy_task_digest, legacy_event_digest)
            steps.append(self._step(engine, "second-head-upgrade"))

            command.downgrade(config, "base")
            self._assert_revision(engine, "base")
            final_step = self._step(engine, "base-cleanup")
            if _APPLICATION_TABLES.intersection(final_step.tables):
                raise MigrationRehearsalError("base downgrade left application tables")
            steps.append(final_step)

            result = MigrationRehearsalResult(
                revision_cycle=[step.revision for step in steps],
                legacy_task_digest=legacy_task_digest,
                legacy_event_digest=legacy_event_digest,
                first_upgrade_payload_digest=first_event_digest,
                second_upgrade_payload_digest=second_event_digest,
                semantic_digests_stable=True,
                replay_digests_valid=first_event_digest == second_event_digest,
                steps=steps,
            )
            if not result.replay_digests_valid:
                raise MigrationRehearsalError("replayed event digest changed across upgrades")
            (root / "migration-rehearsal.json").write_text(
                result.model_dump_json(by_alias=True, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            return result
        except MigrationRehearsalError:
            raise
        except Exception as exc:
            raise MigrationRehearsalError("migration rehearsal failed closed") from exc
        finally:
            engine.dispose()

    @staticmethod
    def _prepare_empty_output(root: Path) -> None:
        if root.exists():
            if not root.is_dir():
                raise MigrationRehearsalError("output root must be an empty directory")
            if any(root.iterdir()):
                raise MigrationRehearsalError("output root must be empty")
            return
        root.mkdir(parents=True)

    def _config(self, database_url: str) -> Config:
        if not self._alembic_config.is_file():
            raise MigrationRehearsalError("Alembic configuration is unavailable")
        file_config = Config(str(self._alembic_config))
        script_location = file_config.get_main_option("script_location")
        if not script_location:
            raise MigrationRehearsalError("Alembic script location is unavailable")
        # Embedded evidence commands keep stdout machine-readable. The regular
        # Alembic CLI still loads the repository logging configuration.
        config = Config()
        config.set_main_option("script_location", script_location)
        config.set_main_option("sqlalchemy.url", database_url)
        return config

    @staticmethod
    def _seed_legacy_rows(engine: Engine) -> None:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO tasks "
                    "(task_id, title, repository_uri, issue, acceptance_criteria, "
                    "allowed_paths, status, plan_version, created_at) VALUES "
                    "(:task_id, :title, :repository_uri, :issue, :acceptance, "
                    ":allowed, :status, :plan_version, :created_at)"
                ),
                {
                    "task_id": _TASK_ID,
                    "title": "Migration rehearsal",
                    "repository_uri": "fixture://migration-rehearsal",
                    "issue": "Preserve legacy task data",
                    "acceptance": '["legacy row survives"]',
                    "allowed": '["src/**"]',
                    "status": "PLANNED",
                    "plan_version": 1,
                    "created_at": "2026-08-14 00:00:00",
                },
            )
            connection.execute(
                text(
                    "INSERT INTO task_events "
                    "(event_id, task_id, from_status, to_status, plan_version, reason, "
                    "created_at) VALUES (:event_id, :task_id, :from_status, :to_status, "
                    ":plan_version, :reason, :created_at)"
                ),
                {
                    "event_id": _EVENT_ID,
                    "task_id": _TASK_ID,
                    "from_status": "RECEIVED",
                    "to_status": "PLANNED",
                    "plan_version": 1,
                    "reason": "legacy migration rehearsal",
                    "created_at": "2026-08-14 00:00:01",
                },
            )

    @classmethod
    def _legacy_digests(cls, engine: Engine) -> tuple[str, str]:
        with engine.connect() as connection:
            task = connection.execute(
                text(
                    "SELECT task_id, title, repository_uri, issue, acceptance_criteria, "
                    "allowed_paths, status, plan_version, created_at FROM tasks "
                    "WHERE task_id=:task_id"
                ),
                {"task_id": _TASK_ID},
            ).mappings().one()
            event = connection.execute(
                text(
                    "SELECT event_id, task_id, from_status, to_status, plan_version, "
                    "reason, created_at FROM task_events WHERE event_id=:event_id"
                ),
                {"event_id": _EVENT_ID},
            ).mappings().one()
        return cls._digest(dict(task)), cls._digest(dict(event))

    @classmethod
    def _assert_legacy_digests(
        cls,
        engine: Engine,
        expected_task: str,
        expected_event: str,
    ) -> None:
        actual_task, actual_event = cls._legacy_digests(engine)
        if (actual_task, actual_event) != (expected_task, expected_event):
            raise MigrationRehearsalError("legacy semantic digest changed")

    @staticmethod
    def _digest(row: Mapping[str, object]) -> str:
        payload = {key: str(value) for key, value in sorted(row.items())}
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _validated_event_digest(database_url: str) -> str:
        events = Database(database_url).list_task_events(_TASK_ID)
        if len(events) != 1 or not events[0].has_valid_payload_digest():
            raise MigrationRehearsalError("replayed task event is invalid")
        return events[0].payload_digest

    @staticmethod
    def _assert_legacy_schema(engine: Engine) -> None:
        tables = set(inspect(engine).get_table_names())
        if "tool_calls" in tables or "consumed_grant_nonces" in tables:
            raise MigrationRehearsalError("legacy rollback retained newer tables")
        columns = {column["name"] for column in inspect(engine).get_columns("task_events")}
        if {"schema_version", "payload_digest"}.intersection(columns):
            raise MigrationRehearsalError("legacy rollback retained replay columns")

    @staticmethod
    def _step(engine: Engine, name: str) -> MigrationStep:
        tables = sorted(inspect(engine).get_table_names())
        with engine.connect() as connection:
            task_count = (
                connection.scalar(text("SELECT COUNT(*) FROM tasks")) if "tasks" in tables else 0
            )
            event_count = (
                connection.scalar(text("SELECT COUNT(*) FROM task_events"))
                if "task_events" in tables
                else 0
            )
        revision = MigrationRehearsal._revision(engine)
        return MigrationStep(
            name=name,
            revision=revision,
            tables=tables,
            task_count=int(task_count or 0),
            event_count=int(event_count or 0),
        )

    @staticmethod
    def _revision(engine: Engine) -> str:
        with engine.connect() as connection:
            revision = MigrationContext.configure(connection).get_current_revision()
        return revision or "base"

    @staticmethod
    def _assert_revision(engine: Engine, expected: str) -> None:
        actual = MigrationRehearsal._revision(engine)
        if actual != expected:
            raise MigrationRehearsalError(
                f"unexpected migration revision: expected {expected}, got {actual}"
            )
