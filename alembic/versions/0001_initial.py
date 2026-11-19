"""initial tables

Revision ID: 0001
Revises:
Create Date: 2026-11-19
"""

import sqlalchemy as sa

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "campaigns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("keitaro_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("geo", sa.String(2), nullable=False),
        sa.Column("offer_id", sa.Integer(), nullable=False),
        sa.Column("domain_id", sa.Integer(), nullable=True),
        sa.Column("group_id", sa.Integer(), nullable=True),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_campaigns_keitaro_id", "campaigns", ["keitaro_id"], unique=True)
    op.create_table(
        "offer_changes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "campaign_id", sa.Integer(), sa.ForeignKey("campaigns.id"), nullable=False
        ),
        sa.Column("offer_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_offer_changes_campaign_id", "offer_changes", ["campaign_id"])


def downgrade() -> None:
    op.drop_index("ix_offer_changes_campaign_id", table_name="offer_changes")
    op.drop_table("offer_changes")
    op.drop_index("ix_campaigns_keitaro_id", table_name="campaigns")
    op.drop_table("campaigns")
