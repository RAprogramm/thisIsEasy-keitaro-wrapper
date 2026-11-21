"""Campaign editor endpoints: thin HTTP layer over ``app.editor_service``."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..cache import TtlCache
from ..db import get_db
from ..editor_service import (
    ACTIVE_STATUSES,
    REMOVED_STATUSES,
    build_campaign_view,
    ensure_pin_allowed,
    ensure_removal_keeps_shares,
    ensure_shares_publishable,
    is_dirty,
    local_offers,
    log_change,
    offer_stream,
    rebalance,
    resolve_offer_stream,
    stream_payload,
    sync_stream,
    unlog_change,
)
from ..keitaro import KeitaroClient, ensure_offer_exists, get_client
from ..models import OfferStatus, StreamOffer
from ..schemas import CampaignView, DictItem, OfferAdd
from ..search import search_items

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/campaigns", tags=["editor"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
Tracker = Annotated[KeitaroClient, Depends(get_client)]

_campaigns_cache: TtlCache[list[DictItem]] = TtlCache(ttl=5.0)


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

    return search_items(await _campaigns_cache.aget_or_set(fetch), q, limit)


@router.get("/{campaign_id}")
async def get_campaign_endpoint(
    campaign_id: int,
    k: Tracker,
    db: DbSession,
    date_from: Annotated[str | None, Query(alias="from")] = None,
    date_to: Annotated[str | None, Query(alias="to")] = None,
) -> CampaignView:
    """Full campaign payload: streams, offers, statistics and dirty flags."""
    return await build_campaign_view(campaign_id, k, db, date_from, date_to)


@router.post("/{campaign_id}/offers")
async def add_offer(
    campaign_id: int,
    body: OfferAdd,
    db: DbSession,
    k: Tracker,
) -> CampaignView:
    """Stage an offer addition to a stream; shares are rebalanced, Keitaro untouched."""
    await ensure_offer_exists(k, body.offer_id)
    sid, rows = await resolve_offer_stream(db, k, campaign_id, body.stream_id)

    existing = next((r for r in rows if r.offer_id == body.offer_id), None)
    if existing is not None and existing.status != OfferStatus.REMOVED:
        raise HTTPException(409, "Оффер уже есть в потоке")
    if existing is not None:
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
    await db.flush()
    rows = await local_offers(db, campaign_id, sid)
    rebalance(rows)
    await log_change(db, campaign_id, body.offer_id, "add")
    await db.commit()
    logger.info("added offer %s to campaign %s", body.offer_id, campaign_id)
    return await build_campaign_view(campaign_id, k, db)


@router.delete("/{campaign_id}/offers/{offer_id}")
async def remove_offer(
    campaign_id: int,
    offer_id: int,
    db: DbSession,
    k: Tracker,
    stream_id: int | None = None,
) -> CampaignView:
    """Stage an offer removal: share 0, others rebalanced, archived on push."""
    _, rows = await resolve_offer_stream(db, k, campaign_id, stream_id)
    target = next((r for r in rows if r.offer_id == offer_id), None)
    if target is None or target.status == OfferStatus.REMOVED:
        raise HTTPException(404, "Оффера нет в потоке")
    if target.status == OfferStatus.PENDING_ADD:
        ensure_removal_keeps_shares(rows, target)
        await unlog_change(db, campaign_id, offer_id, "add")
        remaining = [r for r in rows if r is not target]
        rebalance(remaining)
        await db.delete(target)
        await db.commit()
    else:
        remaining_active = [
            r for r in rows if r.status in ACTIVE_STATUSES and r is not target
        ]
        if not remaining_active:
            raise HTTPException(400, "Нельзя удалить последний оффер потока")
        ensure_removal_keeps_shares(rows, target)
        target.status = OfferStatus.PENDING_REMOVE
        target.share = 0
        target.pinned = False
        rebalance(rows)
        await log_change(db, campaign_id, offer_id, "remove")
        await db.commit()
        logger.info("removed offer %s from campaign %s", offer_id, campaign_id)
    return await build_campaign_view(campaign_id, k, db)


@router.post("/{campaign_id}/offers/{offer_id}/restore")
async def restore_offer(
    campaign_id: int,
    offer_id: int,
    db: DbSession,
    k: Tracker,
    stream_id: int | None = None,
) -> CampaignView:
    """Bring an archived offer back; a staged removal is simply undone."""
    _, rows = await resolve_offer_stream(db, k, campaign_id, stream_id)
    target = next((r for r in rows if r.offer_id == offer_id), None)
    if target is None:
        raise HTTPException(404, "Оффер не найден в потоке")
    if target.status == OfferStatus.PENDING_REMOVE:
        target.status = OfferStatus.ACTIVE
        rebalance(rows)
        await unlog_change(db, campaign_id, offer_id, "remove")
        await db.commit()
        logger.info(
            "undid staged removal of offer %s in campaign %s", offer_id, campaign_id
        )
        return await build_campaign_view(campaign_id, k, db)
    if target.status != OfferStatus.REMOVED:
        raise HTTPException(404, "Оффер не в архиве")
    target.status = OfferStatus.PENDING_ADD
    target.share = 0
    target.pinned = False
    rebalance(rows)
    await log_change(db, campaign_id, offer_id, "add")
    await db.commit()
    logger.info("restored offer %s in campaign %s", offer_id, campaign_id)
    return await build_campaign_view(campaign_id, k, db)


@router.post("/{campaign_id}/offers/{offer_id}/pin")
async def pin_offer(
    campaign_id: int,
    offer_id: int,
    db: DbSession,
    k: Tracker,
    stream_id: int | None = None,
    pinned: Annotated[bool, Query()] = True,
) -> CampaignView:
    """Pin or unpin an offer's share; pinned shares survive rebalancing."""
    _, rows = await resolve_offer_stream(db, k, campaign_id, stream_id)
    target = next((r for r in rows if r.offer_id == offer_id), None)
    if target is None or target.status in REMOVED_STATUSES:
        raise HTTPException(404, "Оффер не найден в потоке")
    ensure_pin_allowed(rows, target, pinned)
    target.pinned = pinned
    rebalance(rows)
    await db.commit()
    logger.info(
        "pinned state changed for offer %s in campaign %s", offer_id, campaign_id
    )
    return await build_campaign_view(campaign_id, k, db)


@router.post("/{campaign_id}/push")
async def push_stream(
    campaign_id: int,
    db: DbSession,
    k: Tracker,
    stream_id: int | None = None,
) -> CampaignView:
    """Publish staged changes of a stream to Keitaro."""
    sid, rows = await resolve_offer_stream(db, k, campaign_id, stream_id)
    if not is_dirty(rows):
        return await build_campaign_view(campaign_id, k, db)

    push_offers = [r for r in rows if r.status in ACTIVE_STATUSES]
    ensure_shares_publishable(rows)
    await k.update_stream(sid, stream_payload(push_offers))

    for r in rows:
        if r.status == OfferStatus.PENDING_ADD:
            r.status = OfferStatus.ACTIVE
        elif r.status == OfferStatus.PENDING_REMOVE:
            r.status = OfferStatus.REMOVED
        r.published_share = r.share
        r.published_pinned = r.pinned
    await db.commit()
    logger.info("pushed stream %s of campaign %s", stream_id, campaign_id)
    return await build_campaign_view(campaign_id, k, db)


@router.post("/{campaign_id}/cancel")
async def cancel_stream(
    campaign_id: int,
    db: DbSession,
    k: Tracker,
    stream_id: int | None = None,
) -> CampaignView:
    """Discard staged changes: additions vanish, removals revert to published."""
    stream = offer_stream(await k.campaign_streams(campaign_id), stream_id)
    sid = stream["id"]
    rows = await local_offers(db, campaign_id, sid)
    for r in rows:
        if r.status == OfferStatus.PENDING_ADD:
            await unlog_change(db, campaign_id, r.offer_id, "add")
            await db.delete(r)
        elif r.status == OfferStatus.PENDING_REMOVE:
            await unlog_change(db, campaign_id, r.offer_id, "remove")
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
    await sync_stream(db, campaign_id, sid, stream.get("offers", []))
    return await build_campaign_view(campaign_id, k, db)
