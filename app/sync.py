"""Reconciliation between locally tracked offers and Keitaro streams."""

from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .errors import DomainError
from .keitaro import LANDINGS_SCHEMA, KeitaroClient
from .models import OfferStatus, StreamOffer
from .shares import is_dirty, rebalance


def offer_stream(streams: Any, stream_id: int | None) -> dict[str, Any]:
    """Pick the offer-accepting stream, by id or the first `landings` one."""
    if stream_id is not None:
        for s in streams:
            if s["id"] == stream_id:
                if s.get("schema") != LANDINGS_SCHEMA:
                    raise DomainError("Поток не принимает офферы")
                return cast(dict[str, Any], s)
        raise DomainError("Поток не найден", 404)
    for s in streams:
        if s.get("schema") == LANDINGS_SCHEMA:
            return cast(dict[str, Any], s)
    raise DomainError("В кампании нет потока с офферами")


async def local_offers(
    db: AsyncSession, campaign_id: int, stream_id: int
) -> list[StreamOffer]:
    """All locally tracked offers of one stream."""
    result = await db.execute(
        select(StreamOffer)
        .where(
            StreamOffer.keitaro_campaign_id == campaign_id,
            StreamOffer.stream_id == stream_id,
        )
        .order_by(StreamOffer.id)
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
    externally_removed = False
    for r in rows:
        if r.status == OfferStatus.ACTIVE:
            if r.offer_id not in keitaro_ids:
                r.status = OfferStatus.REMOVED
                externally_removed = True
            else:
                r.ever_published = True
                if (
                    not r.pinned
                    and not dirty
                    and keitaro_share.get(r.offer_id) is not None
                ):
                    r.share = int(cast(Any, keitaro_share[r.offer_id]))
                    r.published_share = r.share
                    r.published_pinned = r.pinned
    if externally_removed:
        rebalance(rows)

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
                    ever_published=True,
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
