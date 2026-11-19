"""tighten created_at and action integrity

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-19
"""

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "campaigns",
        "created_at",
        existing_type=sa.DateTime(),
        existing_nullable=True,
        existing_server_default=sa.text("now()"),
        nullable=False,
    )
    op.alter_column(
        "offer_changes",
        "created_at",
        existing_type=sa.DateTime(),
        existing_nullable=True,
        existing_server_default=sa.text("now()"),
        nullable=False,
    )
    op.create_check_constraint(
        "ck_offer_changes_action", "offer_changes", "action IN ('add', 'remove')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_offer_changes_action", "offer_changes", type_="check")
    op.alter_column(
        "offer_changes",
        "created_at",
        existing_type=sa.DateTime(),
        existing_nullable=False,
        existing_server_default=sa.text("now()"),
        nullable=True,
    )
    op.alter_column(
        "campaigns",
        "created_at",
        existing_type=sa.DateTime(),
        existing_nullable=False,
        existing_server_default=sa.text("now()"),
        nullable=True,
    )
