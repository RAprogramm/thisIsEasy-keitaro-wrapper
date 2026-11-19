"""add idempotency key to campaigns

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-19
"""

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column("idempotency_key", sa.String(64), nullable=True),
    )
    op.create_unique_constraint(
        "uq_campaigns_idempotency_key", "campaigns", ["idempotency_key"]
    )
    op.create_index(
        "ix_campaigns_idempotency_key", "campaigns", ["idempotency_key"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_campaigns_idempotency_key", table_name="campaigns")
    op.drop_constraint("uq_campaigns_idempotency_key", "campaigns", type_="unique")
    op.drop_column("campaigns", "idempotency_key")
