"""SQLAlchemy ORM models for campaigns, offer changes, and tracked stream offers."""

from datetime import datetime
from typing import Literal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

CAMPAIGN_RECORD_STATUSES = ("active", "pending_add", "pending_remove", "removed")


class CampaignRecord(Base):
    """A campaign created through the creator."""

    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    keitaro_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    geo: Mapped[str] = mapped_column(String(2))
    offer_id: Mapped[int] = mapped_column(Integer)
    domain_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    group_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    changes: Mapped[list["OfferChange"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )


class OfferChange(Base):
    """Log of offer additions and removals made in the editor."""

    __tablename__ = "offer_changes"
    __table_args__ = (
        CheckConstraint("action IN ('add', 'remove')", name="ck_offer_changes_action"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), index=True)
    offer_id: Mapped[int] = mapped_column(Integer)
    action: Mapped[Literal["add", "remove"]] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    campaign: Mapped[CampaignRecord] = relationship(back_populates="changes")


class StreamOffer(Base):
    """An offer tracked inside a campaign stream by the editor.

    Statuses:
        active          - present in Keitaro and published.
        pending_add     - added locally, not yet pushed to Keitaro.
        pending_remove  - marked for removal, still in Keitaro until push.
        removed         - archived locally (not in Keitaro), can be brought back.
    """

    __tablename__ = "stream_offers"
    __table_args__ = (
        UniqueConstraint(
            "keitaro_campaign_id",
            "stream_id",
            "offer_id",
            name="uq_stream_offers_campaign_stream_offer",
        ),
        CheckConstraint(
            "status IN ('active', 'pending_add', 'pending_remove', 'removed')",
            name="ck_stream_offers_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    keitaro_campaign_id: Mapped[int] = mapped_column(Integer, index=True)
    stream_id: Mapped[int] = mapped_column(Integer, index=True)
    offer_id: Mapped[int] = mapped_column(Integer)
    share: Mapped[int] = mapped_column(Integer, default=0)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    published_share: Mapped[int] = mapped_column(Integer, default=0)
    published_pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
