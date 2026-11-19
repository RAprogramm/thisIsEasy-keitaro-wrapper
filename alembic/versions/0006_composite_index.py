"""add composite index on stream_offers (campaign, stream)

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-19
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_stream_offers_campaign_stream",
        "stream_offers",
        ["keitaro_campaign_id", "stream_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_stream_offers_campaign_stream", table_name="stream_offers")
