"""editor draft state and timestamptz columns

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-19
"""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # created_at becomes timezone-aware on both existing tables.
    op.alter_column(
        "campaigns",
        "created_at",
        existing_type=sa.DateTime(),
        type_=sa.DateTime(timezone=True),
        existing_nullable=False,
        existing_server_default=sa.text("now()"),
        nullable=False,
    )
    op.alter_column(
        "offer_changes",
        "created_at",
        existing_type=sa.DateTime(),
        type_=sa.DateTime(timezone=True),
        existing_nullable=False,
        existing_server_default=sa.text("now()"),
        nullable=False,
    )

    # Editor draft state: offers tracked inside a campaign stream.
    op.create_table(
        "stream_offers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("keitaro_campaign_id", sa.Integer(), nullable=False, index=True),
        sa.Column("stream_id", sa.Integer(), nullable=False, index=True),
        sa.Column("offer_id", sa.Integer(), nullable=False),
        sa.Column("share", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "pinned", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "published_share", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "published_pinned",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "status", sa.String(16), nullable=False, server_default=sa.text("'active'")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "keitaro_campaign_id",
            "stream_id",
            "offer_id",
            name="uq_stream_offers_campaign_stream_offer",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'pending_add', 'pending_remove', 'removed')",
            name="ck_stream_offers_status",
        ),
    )


def downgrade() -> None:
    op.drop_table("stream_offers")
    op.alter_column(
        "offer_changes",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(),
        existing_nullable=False,
        existing_server_default=sa.text("now()"),
        nullable=False,
    )
    op.alter_column(
        "campaigns",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(),
        existing_nullable=False,
        existing_server_default=sa.text("now()"),
        nullable=False,
    )
