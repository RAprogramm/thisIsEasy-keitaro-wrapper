"""track whether a stream offer has ever been published to Keitaro

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-21
"""

import sqlalchemy as sa

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "stream_offers",
        sa.Column(
            "ever_published", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade() -> None:
    op.drop_column("stream_offers", "ever_published")
