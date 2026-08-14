"""Persist consumed Grant nonce digests across Broker restarts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "consumed_grant_nonces",
        sa.Column("nonce_digest", sa.String(length=64), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("nonce_digest"),
    )


def downgrade() -> None:
    op.drop_table("consumed_grant_nonces")
