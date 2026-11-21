"""Journal of offer additions and removals tied to creator campaigns."""

from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import CampaignRecord, OfferChange


async def campaign_record(
    db: AsyncSession, keitaro_campaign_id: int
) -> CampaignRecord | None:
    """The local record of a campaign created through the creator, if any."""
    result = await db.execute(
        select(CampaignRecord).where(CampaignRecord.keitaro_id == keitaro_campaign_id)
    )
    return result.scalar_one_or_none()


async def log_change(
    db: AsyncSession,
    keitaro_campaign_id: int,
    offer_id: int,
    action: Literal["add", "remove"],
) -> None:
    """Append an add/remove entry to the journal; flushes, the caller commits."""
    rec = await campaign_record(db, keitaro_campaign_id)
    if rec:
        db.add(OfferChange(campaign_id=rec.id, offer_id=offer_id, action=action))
        await db.flush()


async def unlog_change(
    db: AsyncSession,
    keitaro_campaign_id: int,
    offer_id: int,
    action: Literal["add", "remove"],
) -> None:
    """Drop journal entries for a cancelled action; flushes, the caller commits."""
    rec = await campaign_record(db, keitaro_campaign_id)
    if rec:
        result = await db.execute(
            select(OfferChange).where(
                OfferChange.campaign_id == rec.id,
                OfferChange.offer_id == offer_id,
                OfferChange.action == action,
            )
        )
        entries = result.scalars().all()
        for e in entries:
            await db.delete(e)
        if entries:
            await db.flush()
