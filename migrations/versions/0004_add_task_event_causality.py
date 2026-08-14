"""Add replay metadata and payload digests to task events."""

import hashlib
import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA_VERSION = "agentloom.task-event/v1alpha1"
_EVENT_TYPE = "TASK_STATUS_TRANSITION"


def _digest(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def upgrade() -> None:
    op.add_column(
        "task_events",
        sa.Column("schema_version", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "task_events",
        sa.Column("event_type", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "task_events",
        sa.Column("actor", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "task_events",
        sa.Column("causation_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "task_events",
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "task_events",
        sa.Column("payload_digest", sa.String(length=64), nullable=True),
    )

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT event_id, task_id, from_status, to_status, plan_version, reason "
            "FROM task_events ORDER BY task_id, plan_version"
        )
    ).mappings()
    previous_by_task: dict[str, str] = {}
    for row in rows:
        causation_id = previous_by_task.get(row["task_id"])
        payload: dict[str, object] = {
            "schemaVersion": _SCHEMA_VERSION,
            "eventType": _EVENT_TYPE,
            "taskId": row["task_id"],
            "fromStatus": row["from_status"],
            "toStatus": row["to_status"],
            "planVersion": row["plan_version"],
            "reason": row["reason"],
            "actor": "agentloom-workflow",
            "causationId": causation_id,
            "correlationId": row["task_id"],
        }
        connection.execute(
            sa.text(
                "UPDATE task_events SET schema_version=:schema_version, "
                "event_type=:event_type, actor=:actor, causation_id=:causation_id, "
                "correlation_id=:correlation_id, payload_digest=:payload_digest "
                "WHERE event_id=:event_id"
            ),
            {
                "schema_version": _SCHEMA_VERSION,
                "event_type": _EVENT_TYPE,
                "actor": "agentloom-workflow",
                "causation_id": causation_id,
                "correlation_id": row["task_id"],
                "payload_digest": _digest(payload),
                "event_id": row["event_id"],
            },
        )
        previous_by_task[row["task_id"]] = row["event_id"]

    with op.batch_alter_table("task_events") as batch:
        batch.alter_column("schema_version", nullable=False)
        batch.alter_column("event_type", nullable=False)
        batch.alter_column("actor", nullable=False)
        batch.alter_column("correlation_id", nullable=False)
        batch.alter_column("payload_digest", nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("task_events") as batch:
        batch.drop_column("payload_digest")
        batch.drop_column("correlation_id")
        batch.drop_column("causation_id")
        batch.drop_column("actor")
        batch.drop_column("event_type")
        batch.drop_column("schema_version")
