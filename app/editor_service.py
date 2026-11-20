"""Editor domain logic: stream resolution, share rebalancing, Keitaro sync, journal.

The router in ``app.routers.editor`` stays thin: it parses requests and delegates
everything that decides *what happens* to campaigns and offers to this module.
"""

import logging
from typing import Any, Literal, cast

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .keitaro import LANDINGS_SCHEMA, KeitaroClient
from .models import CampaignRecord, OfferChange, OfferStatus, StreamOffer
from .schemas import (
    CampaignView,
    OfferStats,
    OfferView,
    StreamView,
)

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = (OfferStatus.ACTIVE, OfferStatus.PENDING_ADD)
REMOVED_STATUSES = (OfferStatus.PENDING_REMOVE, OfferStatus.REMOVED)


def offer_stream(streams: Any, stream_id: int | None) -> dict[str, Any]:
    """Pick the offer-accepting stream, by id or the first `landings` one."""
    if stream_id is not None:
        for s in streams:
            if s["id"] == stream_id:
                if s.get("schema") != LANDINGS_SCHEMA:
                    raise HTTPException(400, "Поток не принимает офферы")
                return cast(dict[str, Any], s)
        raise HTTPException(404, "Поток не найден")
    for s in streams:
        if s.get("schema") == LANDINGS_SCHEMA:
            return cast(dict[str, Any], s)
    raise HTTPException(400, "В кампании нет потока с офферами")


def rebalance(offers: list[StreamOffer]) -> list[StreamOffer]:
    """Split 100% across non-pinned active offers; removed ones get 0."""
    pinned_sum = sum(
        o.share for o in offers if o.pinned and o.status in ACTIVE_STATUSES
    )
    participants = [o for o in offers if not o.pinned and o.status in ACTIVE_STATUSES]
    # Never hand out negative shares: if pinned offers already fill (or
    # overfill) the 100%, unpinned participants simply receive nothing.
    remaining = max(0, 100 - pinned_sum)
    for o in offers:
        if o.status in REMOVED_STATUSES:
            o.share = 0
    if participants:
        base, rest = divmod(remaining, len(participants))
        for i, o in enumerate(participants):
            o.share = base + (rest if i == 0 else 0)
    return offers


def stream_payload(offers: list[StreamOffer]) -> dict[str, Any]:
    """Keitaro PUT updates only the fields sent, so we send just the offer list."""
    return {
        "offers": [
            {
                "offer_id": o.offer_id,
                "share": o.share,
                "state": OfferStatus.ACTIVE,
            }
            for o in offers
            if o.status in ACTIVE_STATUSES
        ]
    }


def is_dirty(offers: list[StreamOffer]) -> bool:
    """True when local state differs from what was last published to Keitaro."""
    return any(
        o.status in (OfferStatus.PENDING_ADD, OfferStatus.PENDING_REMOVE)
        or o.share != o.published_share
        or o.pinned != o.published_pinned
        for o in offers
    )


async def local_offers(
    db: AsyncSession, campaign_id: int, stream_id: int
) -> list[StreamOffer]:
    """All locally tracked offers of one stream."""
    result = await db.execute(
        select(StreamOffer).where(
            StreamOffer.keitaro_campaign_id == campaign_id,
            StreamOffer.stream_id == stream_id,
        )
    )
    return list(result.scalars().all())


async def sync_stream(
    db: AsyncSession,
    campaign_id: int,
    stream_id: int,
    keitaro_offers: Any,
) -> list[StreamOffer]:
    """Reconcile local tracked offers with the current Keitaro stream state."""
    keitaro_ids = {o["offer_id"] for o in keitaro_offers}
    keitaro_share = {o["offer_id"]: o.get("share") for o in keitaro_offers}

    rows = await local_offers(db, campaign_id, stream_id)
    dirty = is_dirty(rows)
    for r in rows:
        if r.status == OfferStatus.ACTIVE:
            if r.offer_id not in keitaro_ids:
                r.status = OfferStatus.REMOVED
            elif (
                not r.pinned and not dirty and keitaro_share.get(r.offer_id) is not None
            ):
                r.share = int(cast(Any, keitaro_share[r.offer_id]))
                r.published_share = r.share
                r.published_pinned = r.pinned

    known = {r.offer_id for r in rows}
    for o in keitaro_offers:
        oid = o["offer_id"]
        if oid not in known:
            db.add(
                StreamOffer(
                    keitaro_campaign_id=campaign_id,
                    stream_id=stream_id,
                    offer_id=oid,
                    share=int(o.get("share", 0)),
                    pinned=False,
                    published_share=int(o.get("share", 0)),
                    published_pinned=False,
                    status=OfferStatus.ACTIVE,
                )
            )
    await db.commit()
    return await local_offers(db, campaign_id, stream_id)


async def resolve_offer_stream(
    db: AsyncSession,
    k: KeitaroClient,
    campaign_id: int,
    stream_id: int | None,
) -> tuple[int, list[StreamOffer]]:
    """Locate the offer stream, sync it with Keitaro, and return (id, rows)."""
    stream = offer_stream(await k.campaign_streams(campaign_id), stream_id)
    sid = stream["id"]
    await sync_stream(db, campaign_id, sid, stream.get("offers", []))
    rows = await local_offers(db, campaign_id, sid)
    return sid, rows


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


def _zero_stats() -> OfferStats:
    return OfferStats(
        clicks=0, unique_clicks=0, conversions=0, revenue=0, cost=0, profit=0
    )


async def _stats_by_offer(
    k: KeitaroClient,
    campaign_id: int,
    date_from: str | None = None,
    date_to: str | None = None,
) -> tuple[dict[int, OfferStats], str | None]:
    try:
        rep = await k.report(
            campaign_id,
            ["offer_id"],
            interval="all_time",
            date_from=date_from,
            date_to=date_to,
        )
    except HTTPException as e:
        return {}, str(e.detail)
    out: dict[int, OfferStats] = {}
    for row in rep.get("rows", []):
        oid = row.get("offer_id")
        if oid is not None:
            out[int(oid)] = OfferStats(
                clicks=row.get("clicks", 0),
                unique_clicks=row.get("campaign_unique_clicks", 0),
                conversions=row.get("conversions", 0),
                revenue=row.get("revenue", 0),
                cost=row.get("cost", 0),
                profit=row.get("profit", 0),
            )
    return out, None


async def build_campaign_view(
    campaign_id: int,
    k: KeitaroClient,
    db: AsyncSession,
    date_from: str | None = None,
    date_to: str | None = None,
) -> CampaignView:
    """Assemble the full editor payload: streams, offers, stats, dirty flags."""
    campaign = await k.get_campaign(campaign_id)
    streams = await k.campaign_streams(campaign_id)
    stats, stats_error = await _stats_by_offer(k, campaign_id, date_from, date_to)
    names = {o["id"]: o["name"] for o in await k.offers()}

    result_streams = []
    for s in streams:
        sid = s["id"]
        if s.get("schema") == LANDINGS_SCHEMA:
            keitaro_offers = s.get("offers", [])
            offers_rows = await sync_stream(db, campaign_id, sid, keitaro_offers)
        else:
            offers_rows = await local_offers(db, campaign_id, sid)

        offers = []
        for o in offers_rows:
            oid = o.offer_id
            offers.append(
                OfferView(
                    offer_id=oid,
                    name=names.get(oid, f"#{oid}"),
                    share=o.share,
                    state="active" if o.status in ACTIVE_STATUSES else "removed",
                    status=o.status,
                    pinned=o.pinned,
                    stats=stats.get(oid, _zero_stats())
                    if o.status in ACTIVE_STATUSES
                    else _zero_stats(),
                )
            )
        result_streams.append(
            StreamView(
                id=sid,
                name=s.get("name"),
                schema=s.get("schema"),
                offers=offers,
                dirty=is_dirty(offers_rows),
            )
        )
    return CampaignView(
        id=campaign["id"],
        name=campaign["name"],
        streams=result_streams,
        stats_error=stats_error,
        keitaro_url=settings.keitaro_url,
    )
