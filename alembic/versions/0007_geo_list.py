"""widen campaigns.geo to hold comma-separated country codes

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-21
"""

import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("campaigns", "geo", existing_type=sa.String(2), type_=sa.String(64))


def downgrade() -> None:
    op.alter_column("campaigns", "geo", existing_type=sa.String(64), type_=sa.String(2))
