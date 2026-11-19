"""add on-delete cascade to offer_changes foreign key

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-19
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "offer_changes_campaign_id_fkey", "offer_changes", type_="foreignkey"
    )
    op.create_foreign_key(
        "offer_changes_campaign_id_fkey",
        "offer_changes",
        "campaigns",
        ["campaign_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "offer_changes_campaign_id_fkey", "offer_changes", type_="foreignkey"
    )
    op.create_foreign_key(
        "offer_changes_campaign_id_fkey",
        "offer_changes",
        "campaigns",
        ["campaign_id"],
        ["id"],
    )
