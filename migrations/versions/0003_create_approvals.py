"""Create parameter-bound human approval ledger."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "approvals",
        sa.Column("approval_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("grant_id", sa.String(length=64), nullable=False),
        sa.Column("parameter_digest", sa.String(length=64), nullable=False),
        sa.Column("risk_level", sa.String(length=2), nullable=False),
        sa.Column("route_id", sa.String(length=200), nullable=False),
        sa.Column("rollback_plan_hash", sa.String(length=64), nullable=False),
        sa.Column("action_summary", sa.Text(), nullable=False),
        sa.Column("requested_by", sa.String(length=200), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("approval_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_by", sa.String(length=200), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.task_id"]),
        sa.PrimaryKeyConstraint("approval_id"),
    )
    op.create_index("ix_approvals_task_id", "approvals", ["task_id"])
    op.create_index("ix_approvals_grant_id", "approvals", ["grant_id"])


def downgrade() -> None:
    op.drop_index("ix_approvals_grant_id", table_name="approvals")
    op.drop_index("ix_approvals_task_id", table_name="approvals")
    op.drop_table("approvals")
