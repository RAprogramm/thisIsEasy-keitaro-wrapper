"""Campaign editor: streams, offers, shares, and draft/publish workflow."""

import logging
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..cache import TtlCache
from ..config import settings
from ..db import get_db
from ..keitaro import KeitaroClient, get_client
from ..models import CampaignRecord, OfferChange, OfferStatus, StreamOffer
from ..schemas import (
    CampaignView,
    DictItem,
    OfferAdd,
    OfferStats,
    OfferView,
    StreamView,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/campaigns", tags=["editor"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
Tracker = Annotated[KeitaroClient, Depends(get_client)]

ACTIVE_STATUSES = (OfferStatus.ACTIVE, OfferStatus.PENDING_ADD)
REMOVED_STATUSES = (OfferStatus.PENDING_REMOVE, OfferStatus.REMOVED)

_campaigns_cache: TtlCache[list[DictItem]] = TtlCache(ttl=5.0)


def _offer_stream(streams: Any, stream_id: int | None) -> dict[str, Any]:
    if stream_id is not None:
        for s in streams:
            if s["id"] == stream_id:
                if s.get("schema") != "landings":
                    raise HTTPException(400, "Поток не принимает офферы")
                return cast(dict[str, Any], s)
        raise HTTPException(404, "Поток не найден")
    for s in streams:
        if s.get("schema") == "landings":
            return cast(dict[str, Any], s)
    raise HTTPException(400, "В кампании нет потока с офферами")


def _rebalance(offers: list[StreamOffer]) -> list[StreamOffer]:
    """Split 100% across non-pinned active offers; removed ones get 0."""
    pinned_sum = sum(
        o.share for o in offers if o.pinned and o.status in ACTIVE_STATUSES
    )
    participants = [o for o in offers if not o.pinned and o.status in ACTIVE_STATUSES]
    remaining = 100 - pinned_sum
    for o in offers:
        if o.status in REMOVED_STATUSES:
            o.share = 0
    if participants:
        base, rest = divmod(remaining, len(participants))
        for i, o in enumerate(participants):
            o.share = base + (rest if i == 0 else 0)
    return offers


def _stream_payload(offers: list[StreamOffer]) -> dict[str, Any]:
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


async def _local_offers(
    db: AsyncSession, campaign_id: int, stream_id: int
) -> list[StreamOffer]:
    result = await db.execute(
        select(StreamOffer).where(
            StreamOffer.keitaro_campaign_id == campaign_id,
            StreamOffer.stream_id == stream_id,
        )
    )
    return list(result.scalars().all())


async def _sync_stream(
    db: AsyncSession,
    campaign_id: int,
    stream_id: int,
    keitaro_offers: Any,
) -> list[StreamOffer]:
    """Reconcile local tracked offers with the current Keitaro stream state."""
    keitaro_ids = {o["offer_id"] for o in keitaro_offers}
    keitaro_share = {o["offer_id"]: o.get("share") for o in keitaro_offers}

    rows = await _local_offers(db, campaign_id, stream_id)
    dirty = _is_dirty(rows)
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
    return await _local_offers(db, campaign_id, stream_id)


def _is_dirty(offers: list[StreamOffer]) -> bool:
    return any(
        o.status in (OfferStatus.PENDING_ADD, OfferStatus.PENDING_REMOVE)
        or o.share != o.published_share
        or o.pinned != o.published_pinned
        for o in offers
    )


async def _log(
    db: AsyncSession,
    keitaro_campaign_id: int,
    offer_id: int,
    action: Literal["add", "remove"],
) -> None:
    result = await db.execute(
        select(CampaignRecord).where(CampaignRecord.keitaro_id == keitaro_campaign_id)
    )
    rec = result.scalar_one_or_none()
    if rec:
        db.add(OfferChange(campaign_id=rec.id, offer_id=offer_id, action=action))
        await db.commit()


async def _unlog(
    db: AsyncSession,
    keitaro_campaign_id: int,
    offer_id: int,
    action: Literal["add", "remove"],
) -> None:
    result = await db.execute(
        select(CampaignRecord).where(CampaignRecord.keitaro_id == keitaro_campaign_id)
    )
    rec = result.scalar_one_or_none()
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
            await db.commit()


async def get_campaign(
    campaign_id: int,
    k: Tracker,
    db: DbSession,
    date_from: str | None = None,
    date_to: str | None = None,
) -> CampaignView:
    campaign = await k.get_campaign(campaign_id)
    streams = await k.campaign_streams(campaign_id)
    stats, stats_error = await _stats_by_offer(k, campaign_id, date_from, date_to)
    names = {o["id"]: o["name"] for o in await k.offers()}

    result_streams = []
    for s in streams:
        sid = s["id"]
        keitaro_offers = s.get("offers", []) if s.get("schema") == "landings" else []
        if s.get("schema") == "landings":
            offers_rows = await _sync_stream(db, campaign_id, sid, keitaro_offers)
        else:
            offers_rows = await _local_offers(db, campaign_id, sid)

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
                dirty=_is_dirty(offers_rows),
            )
        )
    return CampaignView(
        id=campaign["id"],
        name=campaign["name"],
        streams=result_streams,
        stats_error=stats_error,
        keitaro_url=settings.keitaro_url,
    )


@router.get("/search")
async def search_campaigns(
    k: Tracker,
    q: Annotated[str, Query(max_length=100)] = "",
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[DictItem]:
    """Search Keitaro campaigns by name or exact ID for the editor picker.

    The full list is cached for a few seconds so a burst of keystrokes
    produces a single upstream request.
    """

    async def fetch() -> list[DictItem]:
        return [DictItem(id=c["id"], name=c["name"]) for c in await k.all_campaigns()]

    items = await _campaigns_cache.aget_or_set(fetch)
    needle = q.strip().casefold()
    if not needle:
        return items[:limit]
    if needle.isascii() and needle.isdigit():
        exact = [c for c in items if str(c.id) == needle]
        if exact:
            return exact
    return [c for c in items if needle in c.name.casefold()][:limit]


@router.get("/{campaign_id}")
async def get_campaign_endpoint(
    campaign_id: int,
    k: Tracker,
    db: DbSession,
    date_from: Annotated[str | None, Query(alias="from")] = None,
    date_to: Annotated[str | None, Query(alias="to")] = None,
) -> CampaignView:
    return await get_campaign(campaign_id, k, db, date_from, date_to)


@router.post("/{campaign_id}/offers")
async def add_offer(
    campaign_id: int,
    body: OfferAdd,
    db: DbSession,
    k: Tracker,
) -> CampaignView:
    if await k.get_offer(body.offer_id) is None:
        raise HTTPException(400, f"Оффер {body.offer_id} не найден в Keitaro")
    stream = _offer_stream(await k.campaign_streams(campaign_id), body.stream_id)
    sid = stream["id"]
    await _sync_stream(db, campaign_id, sid, stream.get("offers", []))

    rows = await _local_offers(db, campaign_id, sid)
    existing = next((r for r in rows if r.offer_id == body.offer_id), None)
    if existing is not None and existing.status != OfferStatus.REMOVED:
        raise HTTPException(409, "Оффер уже есть в потоке")
    if existing is not None and existing.status == OfferStatus.REMOVED:
        existing.status = OfferStatus.PENDING_ADD
        existing.share = 0
        existing.pinned = False
        existing.published_share = 0
        existing.published_pinned = False
    else:
        db.add(
            StreamOffer(
                keitaro_campaign_id=campaign_id,
                stream_id=sid,
                offer_id=body.offer_id,
                share=0,
                pinned=False,
                status=OfferStatus.PENDING_ADD,
            )
        )
    await db.commit()
    await _log(db, campaign_id, body.offer_id, "add")
    logger.info("added offer %s to campaign %s", body.offer_id, campaign_id)

    rows = await _local_offers(db, campaign_id, sid)
    _rebalance(rows)
    await db.commit()
    return await get_campaign(campaign_id, k, db)


@router.delete("/{campaign_id}/offers/{offer_id}")
async def remove_offer(
    campaign_id: int,
    offer_id: int,
    db: DbSession,
    k: Tracker,
    stream_id: int | None = None,
) -> CampaignView:
    stream = _offer_stream(await k.campaign_streams(campaign_id), stream_id)
    sid = stream["id"]
    await _sync_stream(db, campaign_id, sid, stream.get("offers", []))

    rows = await _local_offers(db, campaign_id, sid)
    target = next((r for r in rows if r.offer_id == offer_id), None)
    if target is None or target.status == OfferStatus.REMOVED:
        raise HTTPException(404, "Оффера нет в потоке")
    if target.status == OfferStatus.PENDING_ADD:
        await _unlog(db, campaign_id, offer_id, "add")
        await db.delete(target)
        await db.commit()
    else:
        target.status = OfferStatus.PENDING_REMOVE
        target.share = 0
        target.pinned = False
        remaining_active = [
            r for r in rows if r.status in ACTIVE_STATUSES and r is not target
        ]
        if not remaining_active:
            await db.rollback()
            raise HTTPException(400, "Нельзя удалить последний оффер потока")
        _rebalance(rows)
        await db.commit()
        await _log(db, campaign_id, offer_id, "remove")
        logger.info("removed offer %s from campaign %s", offer_id, campaign_id)
    return await get_campaign(campaign_id, k, db)


@router.post("/{campaign_id}/offers/{offer_id}/restore")
async def restore_offer(
    campaign_id: int,
    offer_id: int,
    db: DbSession,
    k: Tracker,
    stream_id: int | None = None,
) -> CampaignView:
    stream = _offer_stream(await k.campaign_streams(campaign_id), stream_id)
    sid = stream["id"]
    await _sync_stream(db, campaign_id, sid, stream.get("offers", []))

    rows = await _local_offers(db, campaign_id, sid)
    target = next((r for r in rows if r.offer_id == offer_id), None)
    if target is None or target.status != OfferStatus.REMOVED:
        raise HTTPException(404, "Оффер не в архиве")
    target.status = OfferStatus.PENDING_ADD
    target.share = 0
    target.pinned = False
    _rebalance(rows)
    await db.commit()
    await _log(db, campaign_id, offer_id, "add")
    logger.info("restored offer %s in campaign %s", offer_id, campaign_id)
    return await get_campaign(campaign_id, k, db)


@router.post("/{campaign_id}/offers/{offer_id}/pin")
async def pin_offer(
    campaign_id: int,
    offer_id: int,
    db: DbSession,
    k: Tracker,
    stream_id: int | None = None,
    pinned: Annotated[bool, Query()] = True,
) -> CampaignView:
    stream = _offer_stream(await k.campaign_streams(campaign_id), stream_id)
    sid = stream["id"]
    await _sync_stream(db, campaign_id, sid, stream.get("offers", []))

    rows = await _local_offers(db, campaign_id, sid)
    target = next((r for r in rows if r.offer_id == offer_id), None)
    if target is None or target.status in REMOVED_STATUSES:
        raise HTTPException(404, "Оффер не найден в потоке")
    target.pinned = pinned
    _rebalance(rows)
    await db.commit()
    logger.info(
        "pinned state changed for offer %s in campaign %s", offer_id, campaign_id
    )
    return await get_campaign(campaign_id, k, db)


@router.post("/{campaign_id}/push")
async def push_stream(
    campaign_id: int,
    db: DbSession,
    k: Tracker,
    stream_id: int | None = None,
) -> CampaignView:
    stream = _offer_stream(await k.campaign_streams(campaign_id), stream_id)
    sid = stream["id"]
    await _sync_stream(db, campaign_id, sid, stream.get("offers", []))

    rows = await _local_offers(db, campaign_id, sid)
    if not _is_dirty(rows):
        return await get_campaign(campaign_id, k, db)

    push_offers = [r for r in rows if r.status in ACTIVE_STATUSES]
    await k.update_stream(sid, _stream_payload(push_offers))

    for r in rows:
        if r.status == OfferStatus.PENDING_ADD:
            r.status = OfferStatus.ACTIVE
        elif r.status == OfferStatus.PENDING_REMOVE:
            r.status = OfferStatus.REMOVED
        r.published_share = r.share
        r.published_pinned = r.pinned
    await db.commit()
    logger.info("pushed stream %s of campaign %s", stream_id, campaign_id)
    return await get_campaign(campaign_id, k, db)


@router.post("/{campaign_id}/cancel")
async def cancel_stream(
    campaign_id: int,
    db: DbSession,
    k: Tracker,
    stream_id: int | None = None,
) -> CampaignView:
    stream = _offer_stream(await k.campaign_streams(campaign_id), stream_id)
    sid = stream["id"]
    rows = await _local_offers(db, campaign_id, sid)
    for r in rows:
        if r.status == OfferStatus.PENDING_ADD:
            await _unlog(db, campaign_id, r.offer_id, "add")
            await db.delete(r)
        elif r.status == OfferStatus.PENDING_REMOVE:
            await _unlog(db, campaign_id, r.offer_id, "remove")
            r.status = OfferStatus.ACTIVE
            r.share = r.published_share
            r.pinned = r.published_pinned
        else:
            r.share = r.published_share
            r.pinned = r.published_pinned
    await db.commit()
    logger.info(
        "cancelled staged changes for stream %s of campaign %s", stream_id, campaign_id
    )
    await _sync_stream(db, campaign_id, sid, stream.get("offers", []))
    return await get_campaign(campaign_id, k, db)
