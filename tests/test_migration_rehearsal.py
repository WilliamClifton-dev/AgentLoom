from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect
from typer.testing import CliRunner

from agentloom.cli import app
from agentloom.migration_rehearsal import MigrationRehearsal, MigrationRehearsalError

ROOT = Path(__file__).resolve().parents[1]


def test_rehearsal_preserves_legacy_rows_and_replay_digests(tmp_path: Path) -> None:
    output_root = tmp_path / "rehearsal"

    result = MigrationRehearsal(ROOT / "alembic.ini").run(output_root)

    assert result.status == "PASS"
    assert [step.revision for step in result.steps] == [
        "0003",
        "0006",
        "0003",
        "0006",
        "base",
    ]
    assert result.semantic_digests_stable is True
    assert result.replay_digests_valid is True
    assert result.first_upgrade_payload_digest == result.second_upgrade_payload_digest
    assert len(result.legacy_task_digest) == 64
    assert len(result.legacy_event_digest) == 64
    assert result.steps[0].task_count == 1
    assert result.steps[0].event_count == 1
    assert result.steps[1].task_count == 1
    assert result.steps[2].task_count == 1
    assert result.steps[3].task_count == 1
    assert result.steps[4].task_count == 0
    assert result.steps[4].event_count == 0

    evidence_path = output_root / "migration-rehearsal.json"
    evidence_text = evidence_path.read_text(encoding="utf-8")
    assert str(tmp_path) not in evidence_text
    assert json.loads(evidence_text) == result.model_dump(by_alias=True, mode="json")

    final_tables = set(
        inspect(create_engine(f"sqlite:///{output_root / 'rehearsal.db'}")).get_table_names()
    )
    assert final_tables.isdisjoint(
        {"tasks", "task_events", "approvals", "tool_calls", "consumed_grant_nonces"}
    )


def test_rehearsal_rejects_non_empty_output_without_mutation(tmp_path: Path) -> None:
    output_root = tmp_path / "occupied"
    output_root.mkdir()
    marker = output_root / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(MigrationRehearsalError, match="empty"):
        MigrationRehearsal(ROOT / "alembic.ini").run(output_root)

    assert marker.read_text(encoding="utf-8") == "keep"
    assert sorted(path.name for path in output_root.iterdir()) == ["keep.txt"]


def test_rehearsal_rejects_symlink_output_without_touching_target(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    output_root = tmp_path / "linked-output"
    try:
        output_root.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")

    with pytest.raises(MigrationRehearsalError, match="empty directory"):
        MigrationRehearsal(ROOT / "alembic.ini").run(output_root)

    assert list(target.iterdir()) == []


def test_rehearse_migration_cli_writes_redacted_summary(tmp_path: Path) -> None:
    output_root = tmp_path / "cli-rehearsal"

    result = CliRunner().invoke(
        app,
        ["rehearse-migration", "--output-root", str(output_root)],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "evidenceFile": "migration-rehearsal.json",
        "revisionCycle": ["0003", "0006", "0003", "0006", "base"],
        "status": "PASS",
    }
    assert str(tmp_path) not in result.output
    assert (output_root / "migration-rehearsal.json").is_file()
