"""Campaign creator endpoints: dictionaries and campaign creation."""

import logging
import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..cache import TtlCache
from ..config import settings
from ..db import get_db
from ..keitaro import KeitaroClient, get_client
from ..models import CampaignRecord
from ..schemas import (
    CampaignCreate,
    CampaignCreated,
    CampaignListItem,
    Dictionaries,
    DictItem,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["creator"])

DbSession = Annotated[Session, Depends(get_db)]
Tracker = Annotated[KeitaroClient, Depends(get_client)]

_dictionaries_cache: TtlCache[Dictionaries] = TtlCache(ttl=settings.dictionaries_ttl)


def _pick(items: list[dict[str, Any]], wanted: int | None, label: str) -> int:
    if wanted is not None:
        if not any(i["id"] == wanted for i in items):
            raise HTTPException(400, f"{label} с id={wanted} не найден в Keitaro")
        return wanted
    if not items:
        raise HTTPException(400, f"В Keitaro нет ни одного значения для: {label}")
    return int(items[0]["id"])


def _create_campaign_with_retry(k: KeitaroClient, payload: dict[str, Any]) -> Any:
    """Create the campaign, retrying when Keitaro rejects a colliding alias."""
    remaining = 3
    while True:
        remaining -= 1
        try:
            return k.create_campaign({**payload, "alias": secrets.token_hex(6)})
        except HTTPException as e:
            if remaining == 0 or "alias" not in str(e.detail).lower():
                raise


def _geo_stream_payload(campaign_id: int, geo: str) -> dict[str, Any]:
    """Stream that redirects visitors from the target country to Google."""
    return {
        "campaign_id": campaign_id,
        "name": f"{geo} -> Google",
        "type": "regular",
        "position": 1,
        "weight": 100,
        "state": "active",
        "collect_clicks": True,
        "schema": "redirect",
        "action_type": "http",
        "action_payload": settings.google_url,
        "filter_or": False,
        "filters": [{"name": "country", "mode": "accept", "payload": [geo]}],
    }


def _offer_stream_payload(campaign_id: int, offer_id: int) -> dict[str, Any]:
    """Catch-all stream that serves the chosen offer to everyone else."""
    return {
        "campaign_id": campaign_id,
        "name": "Offer",
        "type": "regular",
        "position": 2,
        "weight": 100,
        "state": "active",
        "collect_clicks": True,
        "schema": "landings",
        "action_type": "http",
        "filter_or": False,
        "filters": [],
        "offers": [{"offer_id": offer_id, "share": 100, "state": "active"}],
    }


@router.get("/dictionaries")
def dictionaries(k: Tracker) -> Dictionaries:
    """Dictionaries for the form: domains, groups, sources, offers."""

    def fetch() -> Dictionaries:
        return Dictionaries(
            domains=[DictItem(id=d["id"], name=d["name"]) for d in k.domains()],
            groups=[DictItem(id=g["id"], name=g["name"]) for g in k.groups()],
            sources=[DictItem(id=s["id"], name=s["name"]) for s in k.traffic_sources()],
            offers=[DictItem(id=o["id"], name=o["name"]) for o in k.offers()],
        )

    return _dictionaries_cache.get_or_set(fetch)


@router.post("/campaigns", status_code=201)
def create_campaign(
    body: CampaignCreate,
    db: DbSession,
    k: Tracker,
) -> CampaignCreated:
    offers = k.offers()
    if not any(o["id"] == body.offer_id for o in offers):
        raise HTTPException(400, f"Оффер {body.offer_id} не найден в Keitaro")

    domain_id = _pick(k.domains(), body.domain_id, "домен")
    group_id = _pick(k.groups(), body.group_id, "группа")
    source_id = _pick(k.traffic_sources(), body.source_id, "источник")

    name = (
        body.name
        if body.name.startswith(settings.campaign_prefix)
        else settings.campaign_prefix + body.name
    )

    campaign = _create_campaign_with_retry(
        k,
        {
            "name": name,
            "type": "position",
            "state": "active",
            "domain_id": domain_id,
            "group_id": group_id,
            "traffic_source_id": source_id,
            "cost_type": "CPC",
            "cost_value": 0,
            "cost_currency": "USD",
        },
    )
    cid = campaign["id"]

    try:
        k.create_stream(_geo_stream_payload(cid, body.geo))
        k.create_stream(_offer_stream_payload(cid, body.offer_id))
    except HTTPException:
        try:
            k.delete_campaign(cid)
        except HTTPException as cleanup_error:
            logger.warning(
                "campaign %s created in Keitaro but cleanup failed: %s",
                cid,
                cleanup_error.detail,
            )
        raise

    rec = CampaignRecord(
        keitaro_id=cid,
        name=name,
        geo=body.geo,
        offer_id=body.offer_id,
        domain_id=domain_id,
        group_id=group_id,
        source_id=source_id,
    )
    db.add(rec)
    db.commit()
    return CampaignCreated(
        id=cid,
        name=name,
        domain_id=domain_id,
        group_id=group_id,
        source_id=source_id,
    )


@router.get("/campaigns")
def list_campaigns(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[CampaignListItem]:
    rows = db.scalars(
        select(CampaignRecord).order_by(CampaignRecord.id.desc()).limit(limit)
    ).all()
    return [
        CampaignListItem(
            id=r.keitaro_id, name=r.name, geo=r.geo, created_at=r.created_at
        )
        for r in rows
    ]
