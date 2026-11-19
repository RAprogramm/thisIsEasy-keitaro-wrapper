from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..keitaro import KeitaroClient, get_client
from ..models import CampaignRecord, OfferChange
from ..schemas import OfferAdd

router = APIRouter(prefix="/api/campaigns", tags=["editor"])


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


def _rebalance(offers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Split 100% evenly; the remainder goes to the first offer."""
    n = len(offers)
    if n == 0:
        return offers
    base, rest = divmod(100, n)
    for i, o in enumerate(offers):
        o["share"] = base + (rest if i == 0 else 0)
    return offers


def _stream_payload(
    stream: dict[str, Any], offers: list[dict[str, Any]]
) -> dict[str, Any]:
    """Keitaro PUT updates only the fields sent, so we send just the offer list.

    Filters from the API response are not echoed back: request and response
    use different payload formats.
    """
    return {
        "offers": [
            {
                "offer_id": o["offer_id"],
                "share": o["share"],
                "state": o.get("state", "active"),
            }
            for o in offers
        ]
    }


def _stats_by_offer(
    k: KeitaroClient, campaign_id: int
) -> tuple[dict[int, dict[str, Any]], str | None]:
    """Return (stats by offer id, error message).

    The error is surfaced instead of hidden: zeros in its place would be wrong numbers.
    """
    try:
        rep = k.report(campaign_id, ["offer_id"], interval="all_time")
    except HTTPException as e:
        return {}, str(e.detail)
    out = {}
    for row in rep.get("rows", []):
        oid = row.get("offer_id")
        if oid is not None:
            out[int(oid)] = {
                "clicks": row.get("clicks", 0),
                "unique_clicks": row.get("campaign_unique_clicks", 0),
                "conversions": row.get("conversions", 0),
                "revenue": row.get("revenue", 0),
                "cost": row.get("cost", 0),
                "profit": row.get("profit", 0),
            }
    return out, None


@router.get("/{campaign_id}")
def get_campaign(
    campaign_id: int, k: KeitaroClient = Depends(get_client)
) -> dict[str, Any]:
    campaign = k.get_campaign(campaign_id)
    streams = k.campaign_streams(campaign_id)
    stats, stats_error = _stats_by_offer(k, campaign_id)
    names = {o["id"]: o["name"] for o in k.offers()}

    result_streams = []
    for s in streams:
        offers = []
        for o in s.get("offers", []):
            oid = o["offer_id"]
            offers.append(
                {
                    "offer_id": oid,
                    "name": names.get(oid, f"#{oid}"),
                    "share": o.get("share"),
                    "state": o.get("state"),
                    "stats": stats.get(
                        oid,
                        {
                            "clicks": 0,
                            "unique_clicks": 0,
                            "conversions": 0,
                            "revenue": 0,
                            "cost": 0,
                            "profit": 0,
                        },
                    ),
                }
            )
        result_streams.append(
            {
                "id": s["id"],
                "name": s.get("name"),
                "schema": s.get("schema"),
                "offers": offers,
            }
        )
    return {
        "id": campaign["id"],
        "name": campaign["name"],
        "streams": result_streams,
        "stats_error": stats_error,
    }


@router.post("/{campaign_id}/offers")
def add_offer(
    campaign_id: int,
    body: OfferAdd,
    db: Session = Depends(get_db),
    k: KeitaroClient = Depends(get_client),
) -> dict[str, Any]:
    if not any(o["id"] == body.offer_id for o in k.offers()):
        raise HTTPException(400, f"Оффер {body.offer_id} не найден в Keitaro")
    stream = _offer_stream(k.campaign_streams(campaign_id), body.stream_id)
    offers = list(stream.get("offers", []))
    if any(o["offer_id"] == body.offer_id for o in offers):
        raise HTTPException(409, "Оффер уже есть в потоке")
    offers.append({"offer_id": body.offer_id, "share": 0, "state": "active"})
    k.update_stream(stream["id"], _stream_payload(stream, _rebalance(offers)))
    _log(db, campaign_id, body.offer_id, "add")
    return get_campaign(campaign_id, k)


@router.delete("/{campaign_id}/offers/{offer_id}")
def remove_offer(
    campaign_id: int,
    offer_id: int,
    stream_id: int | None = None,
    db: Session = Depends(get_db),
    k: KeitaroClient = Depends(get_client),
) -> dict[str, Any]:
    stream = _offer_stream(k.campaign_streams(campaign_id), stream_id)
    offers = [o for o in stream.get("offers", []) if o["offer_id"] != offer_id]
    if len(offers) == len(stream.get("offers", [])):
        raise HTTPException(404, "Оффера нет в потоке")
    if not offers:
        raise HTTPException(400, "Нельзя удалить последний оффер потока")
    k.update_stream(stream["id"], _stream_payload(stream, _rebalance(offers)))
    _log(db, campaign_id, offer_id, "remove")
    return get_campaign(campaign_id, k)


def _log(db: Session, keitaro_campaign_id: int, offer_id: int, action: str) -> None:
    rec = db.query(CampaignRecord).filter_by(keitaro_id=keitaro_campaign_id).first()
    if rec:
        db.add(OfferChange(campaign_id=rec.id, offer_id=offer_id, action=action))
        db.commit()
