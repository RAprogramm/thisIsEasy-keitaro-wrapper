"""Campaign editor: streams, offers, shares, and draft/publish workflow."""

import logging
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..keitaro import KeitaroClient, get_client
from ..models import CampaignRecord, OfferChange, StreamOffer
from ..schemas import CampaignView, OfferAdd, OfferStats, OfferView, StreamView

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/campaigns", tags=["editor"])

DbSession = Annotated[Session, Depends(get_db)]
Tracker = Annotated[KeitaroClient, Depends(get_client)]

ACTIVE_STATUSES = ("active", "pending_add")
REMOVED_STATUSES = ("pending_remove", "removed")


def _offer_stream(
    streams: list[dict[str, Any]], stream_id: int | None
) -> dict[str, Any]:
    if stream_id is not None:
        for s in streams:
            if s["id"] == stream_id:
                if s.get("schema") != "landings":
                    raise HTTPException(400, "Поток не принимает офферы")
                return s
        raise HTTPException(404, "Поток не найден")
    for s in streams:
        if s.get("schema") == "landings":
            return s
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
                "state": "active",
            }
            for o in offers
            if o.status in ACTIVE_STATUSES
        ]
    }


def _zero_stats() -> OfferStats:
    return OfferStats(
        clicks=0, unique_clicks=0, conversions=0, revenue=0, cost=0, profit=0
    )


def _stats_by_offer(
    k: KeitaroClient, campaign_id: int
) -> tuple[dict[int, OfferStats], str | None]:
    try:
        rep = k.report(campaign_id, ["offer_id"], interval="all_time")
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


def _local_offers(db: Session, campaign_id: int, stream_id: int) -> list[StreamOffer]:
    return list(
        db.scalars(
            select(StreamOffer).where(
                StreamOffer.keitaro_campaign_id == campaign_id,
                StreamOffer.stream_id == stream_id,
            )
        ).all()
    )


def _sync_stream(
    db: Session,
    campaign_id: int,
    stream_id: int,
    keitaro_offers: list[dict[str, Any]],
) -> list[StreamOffer]:
    """Reconcile local tracked offers with the current Keitaro stream state."""
    keitaro_ids = {o["offer_id"] for o in keitaro_offers}
    keitaro_share = {o["offer_id"]: o.get("share") for o in keitaro_offers}

    rows = _local_offers(db, campaign_id, stream_id)
    dirty = _is_dirty(rows)
    for r in rows:
        if r.status == "active":
            if r.offer_id not in keitaro_ids:
                r.status = "removed"
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
                    status="active",
                )
            )
    db.commit()
    return _local_offers(db, campaign_id, stream_id)


def _is_dirty(offers: list[StreamOffer]) -> bool:
    return any(
        o.status in ("pending_add", "pending_remove")
        or o.share != o.published_share
        or o.pinned != o.published_pinned
        for o in offers
    )


def _log(
    db: Session,
    keitaro_campaign_id: int,
    offer_id: int,
    action: Literal["add", "remove"],
) -> None:
    rec = db.scalars(
        select(CampaignRecord).where(CampaignRecord.keitaro_id == keitaro_campaign_id)
    ).first()
    if rec:
        db.add(OfferChange(campaign_id=rec.id, offer_id=offer_id, action=action))
        db.commit()


def _unlog(
    db: Session,
    keitaro_campaign_id: int,
    offer_id: int,
    action: Literal["add", "remove"],
) -> None:
    rec = db.scalars(
        select(CampaignRecord).where(CampaignRecord.keitaro_id == keitaro_campaign_id)
    ).first()
    if rec:
        entries = db.scalars(
            select(OfferChange).where(
                OfferChange.campaign_id == rec.id,
                OfferChange.offer_id == offer_id,
                OfferChange.action == action,
            )
        ).all()
        for e in entries:
            db.delete(e)
        if entries:
            db.commit()


def get_campaign(
    campaign_id: int, k: Tracker, db: DbSession | None = None
) -> CampaignView:
    if db is None:  # pragma: no cover
        from ..db import SessionLocal

        db = SessionLocal()
        close_after = True
    else:  # pragma: no cover
        close_after = False
    try:  # pragma: no cover
        campaign = k.get_campaign(campaign_id)
        streams = k.campaign_streams(campaign_id)
        stats, stats_error = _stats_by_offer(k, campaign_id)
        names = {o["id"]: o["name"] for o in k.offers()}

        result_streams = []
        for s in streams:
            sid = s["id"]
            keitaro_offers = (
                s.get("offers", []) if s.get("schema") == "landings" else []
            )
            if s.get("schema") == "landings":
                offers_rows = _sync_stream(db, campaign_id, sid, keitaro_offers)
            else:
                offers_rows = _local_offers(db, campaign_id, sid)

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
        )
    finally:  # pragma: no cover
        if close_after:  # pragma: no cover
            db.close()  # pragma: no cover


@router.get("/{campaign_id}")
def get_campaign_endpoint(campaign_id: int, k: Tracker, db: DbSession) -> CampaignView:
    return get_campaign(campaign_id, k, db)


@router.post("/{campaign_id}/offers")
def add_offer(
    campaign_id: int,
    body: OfferAdd,
    db: DbSession,
    k: Tracker,
) -> CampaignView:
    if not any(o["id"] == body.offer_id for o in k.offers()):
        raise HTTPException(400, f"Оффер {body.offer_id} не найден в Keitaro")
    stream = _offer_stream(k.campaign_streams(campaign_id), body.stream_id)
    sid = stream["id"]
    _sync_stream(db, campaign_id, sid, stream.get("offers", []))

    rows = _local_offers(db, campaign_id, sid)
    existing = next((r for r in rows if r.offer_id == body.offer_id), None)
    if existing is not None and existing.status != "removed":
        raise HTTPException(409, "Оффер уже есть в потоке")
    if existing is not None and existing.status == "removed":
        existing.status = "pending_add"
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
                status="pending_add",
            )
        )
    db.commit()
    _log(db, campaign_id, body.offer_id, "add")
    logger.info("added offer %s to campaign %s", body.offer_id, campaign_id)

    rows = _local_offers(db, campaign_id, sid)
    _rebalance(rows)
    db.commit()
    return get_campaign(campaign_id, k, db)


@router.delete("/{campaign_id}/offers/{offer_id}")
def remove_offer(
    campaign_id: int,
    offer_id: int,
    db: DbSession,
    k: Tracker,
    stream_id: int | None = None,
) -> CampaignView:
    stream = _offer_stream(k.campaign_streams(campaign_id), stream_id)
    sid = stream["id"]
    _sync_stream(db, campaign_id, sid, stream.get("offers", []))

    rows = _local_offers(db, campaign_id, sid)
    target = next((r for r in rows if r.offer_id == offer_id), None)
    if target is None or target.status == "removed":
        raise HTTPException(404, "Оффера нет в потоке")
    if target.status == "pending_add":
        _unlog(db, campaign_id, offer_id, "add")
        db.delete(target)
        db.commit()
    else:
        target.status = "pending_remove"
        target.share = 0
        target.pinned = False
        remaining_active = [
            r for r in rows if r.status in ACTIVE_STATUSES and r is not target
        ]
        if not remaining_active:
            db.rollback()
            raise HTTPException(400, "Нельзя удалить последний оффер потока")
        _rebalance(rows)
        db.commit()
        _log(db, campaign_id, offer_id, "remove")
        logger.info("removed offer %s from campaign %s", offer_id, campaign_id)
    return get_campaign(campaign_id, k, db)


@router.post("/{campaign_id}/offers/{offer_id}/restore")
def restore_offer(
    campaign_id: int,
    offer_id: int,
    db: DbSession,
    k: Tracker,
    stream_id: int | None = None,
) -> CampaignView:
    stream = _offer_stream(k.campaign_streams(campaign_id), stream_id)
    sid = stream["id"]
    _sync_stream(db, campaign_id, sid, stream.get("offers", []))

    rows = _local_offers(db, campaign_id, sid)
    target = next((r for r in rows if r.offer_id == offer_id), None)
    if target is None or target.status != "removed":
        raise HTTPException(404, "Оффер не в архиве")
    target.status = "pending_add"
    target.share = 0
    target.pinned = False
    _rebalance(rows)
    db.commit()
    _log(db, campaign_id, offer_id, "add")
    logger.info("restored offer %s in campaign %s", offer_id, campaign_id)
    return get_campaign(campaign_id, k, db)


@router.post("/{campaign_id}/offers/{offer_id}/pin")
def pin_offer(
    campaign_id: int,
    offer_id: int,
    db: DbSession,
    k: Tracker,
    stream_id: int | None = None,
    pinned: Annotated[bool, Query()] = True,
) -> CampaignView:
    stream = _offer_stream(k.campaign_streams(campaign_id), stream_id)
    sid = stream["id"]
    _sync_stream(db, campaign_id, sid, stream.get("offers", []))

    rows = _local_offers(db, campaign_id, sid)
    target = next((r for r in rows if r.offer_id == offer_id), None)
    if target is None or target.status == "removed":
        raise HTTPException(404, "Оффер не найден в потоке")
    target.pinned = pinned
    _rebalance(rows)
    db.commit()
    logger.info(
        "pinned state changed for offer %s in campaign %s", offer_id, campaign_id
    )
    return get_campaign(campaign_id, k, db)


@router.post("/{campaign_id}/push")
def push_stream(
    campaign_id: int,
    db: DbSession,
    k: Tracker,
    stream_id: int | None = None,
) -> CampaignView:
    stream = _offer_stream(k.campaign_streams(campaign_id), stream_id)
    sid = stream["id"]
    _sync_stream(db, campaign_id, sid, stream.get("offers", []))

    rows = _local_offers(db, campaign_id, sid)
    if not _is_dirty(rows):
        return get_campaign(campaign_id, k, db)

    push_offers = [r for r in rows if r.status in ACTIVE_STATUSES]
    k.update_stream(sid, _stream_payload(push_offers))

    for r in rows:
        if r.status == "pending_add":
            r.status = "active"
        elif r.status == "pending_remove":
            r.status = "removed"
        r.published_share = r.share
        r.published_pinned = r.pinned
    db.commit()
    logger.info("pushed stream %s of campaign %s", stream_id, campaign_id)
    return get_campaign(campaign_id, k, db)


@router.post("/{campaign_id}/cancel")
def cancel_stream(
    campaign_id: int,
    db: DbSession,
    k: Tracker,
    stream_id: int | None = None,
) -> CampaignView:
    stream = _offer_stream(k.campaign_streams(campaign_id), stream_id)
    sid = stream["id"]
    rows = _local_offers(db, campaign_id, sid)
    for r in rows:
        if r.status == "pending_add":
            _unlog(db, campaign_id, r.offer_id, "add")
            db.delete(r)
        elif r.status == "pending_remove":
            _unlog(db, campaign_id, r.offer_id, "remove")
            r.status = "active"
            r.share = r.published_share
            r.pinned = r.published_pinned
        else:
            r.share = r.published_share
            r.pinned = r.published_pinned
    db.commit()
    logger.info(
        "cancelled staged changes for stream %s of campaign %s", stream_id, campaign_id
    )
    _sync_stream(db, campaign_id, sid, stream.get("offers", []))
    return get_campaign(campaign_id, k, db)
