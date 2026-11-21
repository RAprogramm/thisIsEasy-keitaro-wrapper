"""Campaign creator endpoints: dictionaries and campaign creation."""

import logging
import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..cache import TtlCache
from ..config import settings
from ..countries import ISO_ALPHA2
from ..db import get_db
from ..errors import AppError, UpstreamError
from ..keitaro import LANDINGS_SCHEMA, KeitaroClient, ensure_offer_exists, get_client
from ..models import CampaignRecord
from ..schemas import (
    CampaignCreate,
    CampaignCreated,
    CampaignListItem,
    Dictionaries,
    DictItem,
)
from ..search import search_items

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["creator"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
Tracker = Annotated[KeitaroClient, Depends(get_client)]

_dictionaries_cache: TtlCache[Dictionaries] = TtlCache(ttl=settings.dictionaries_ttl)


def _pick(items: list[Any], wanted: int | None, label: str) -> int:
    if wanted is not None:
        if not any(i["id"] == wanted for i in items):
            raise HTTPException(400, f"{label} с id={wanted} не найден в Keitaro")
        return wanted
    if not items:
        raise HTTPException(400, f"В Keitaro нет ни одного значения для: {label}")
    return int(items[0]["id"])


async def _create_campaign_with_retry(k: KeitaroClient, payload: dict[str, Any]) -> Any:
    """Create the campaign, retrying when Keitaro rejects a colliding alias."""
    remaining = 3
    while True:
        remaining -= 1
        try:
            return await k.create_campaign({**payload, "alias": secrets.token_hex(6)})
        except UpstreamError as e:
            if remaining == 0 or "alias" not in str(e.detail).lower():
                raise


def _stream_base(campaign_id: int, name: str, position: int) -> dict[str, Any]:
    """Fields shared by every stream the creator builds."""
    return {
        "campaign_id": campaign_id,
        "name": name,
        "type": "regular",
        "position": position,
        "weight": 100,
        "state": "active",
        "collect_clicks": True,
        "filter_or": False,
    }


def _geo_stream_payload(campaign_id: int, geo: str) -> dict[str, Any]:
    """Stream that redirects visitors from the target countries to Google."""
    return {
        **_stream_base(campaign_id, f"{geo} -> Google", 1),
        "schema": "redirect",
        "action_type": "http",
        "action_payload": settings.google_url,
        "filters": [{"name": "country", "mode": "accept", "payload": geo.split(",")}],
    }


def _offer_stream_payload(campaign_id: int, offer_id: int) -> dict[str, Any]:
    """Catch-all stream that serves the chosen offer to everyone else."""
    return {
        **_stream_base(campaign_id, "Offer", 2),
        "schema": LANDINGS_SCHEMA,
        "action_type": "http",
        "filters": [],
        "offers": [{"offer_id": offer_id, "share": 100, "state": "active"}],
    }


async def _discard_campaign(k: KeitaroClient, cid: int) -> None:
    """Best-effort delete of a campaign that cannot be finished locally."""
    try:
        await k.delete_campaign(cid)
    except Exception as cleanup_error:
        logger.warning(
            "campaign %s created in Keitaro but cleanup failed: %s", cid, cleanup_error
        )


async def _load_dictionaries(k: KeitaroClient) -> Dictionaries:
    """Fetch all dictionaries through the shared TTL cache."""

    async def fetch() -> Dictionaries:
        return Dictionaries(
            domains=[DictItem(id=d["id"], name=d["name"]) for d in await k.domains()],
            groups=[DictItem(id=g["id"], name=g["name"]) for g in await k.groups()],
            sources=[
                DictItem(id=s["id"], name=s["name"]) for s in await k.traffic_sources()
            ],
            offers=[DictItem(id=o["id"], name=o["name"]) for o in await k.offers()],
        )

    return await _dictionaries_cache.aget_or_set(fetch)


@router.get("/dictionaries")
async def dictionaries(k: Tracker) -> Dictionaries:
    """Dictionaries for the form: domains, groups, sources, offers.

    Cached per-process for `dictionaries_ttl` seconds; see README "Scaling & state".
    """
    return await _load_dictionaries(k)


@router.get("/countries")
async def countries() -> list[str]:
    """ISO 3166-1 alpha-2 codes accepted by the creator geo field."""
    return sorted(ISO_ALPHA2)


@router.get("/offers/search")
async def search_offers(
    k: Tracker,
    q: Annotated[str, Query(max_length=100)] = "",
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[DictItem]:
    """Search offers by name or exact ID for the editor autocomplete."""
    offers = (await _load_dictionaries(k)).offers
    return search_items(offers, q, limit)


@router.post("/campaigns", status_code=201)
async def create_campaign(
    body: CampaignCreate,
    db: DbSession,
    k: Tracker,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> CampaignCreated:
    if idempotency_key:
        result = await db.execute(
            select(CampaignRecord).where(
                CampaignRecord.idempotency_key == idempotency_key
            )
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            return CampaignCreated(
                id=existing.keitaro_id,
                name=existing.name,
                domain_id=existing.domain_id or 0,
                group_id=existing.group_id or 0,
                source_id=existing.source_id or 0,
            )
    await ensure_offer_exists(k, body.offer_id)

    domain_id = _pick(await k.domains(), body.domain_id, "домен")
    group_id = _pick(await k.groups(), body.group_id, "группа")
    source_id = _pick(await k.traffic_sources(), body.source_id, "источник")

    name = body.name

    campaign = await _create_campaign_with_retry(
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
        await k.create_stream(_geo_stream_payload(cid, body.geo))
        await k.create_stream(_offer_stream_payload(cid, body.offer_id))
    except Exception as stream_error:
        logger.warning("stream creation failed for campaign %s: %s", cid, stream_error)
        await _discard_campaign(k, cid)
        if isinstance(stream_error, AppError):
            raise
        raise HTTPException(
            502, f"Keitaro: {stream_error}"
        ) from stream_error  # pragma: no cover

    try:
        rec = CampaignRecord(
            keitaro_id=cid,
            name=name,
            geo=body.geo,
            offer_id=body.offer_id,
            domain_id=domain_id,
            group_id=group_id,
            source_id=source_id,
            idempotency_key=idempotency_key,
        )
        db.add(rec)
        await db.commit()
    except Exception as db_error:
        logger.exception("failed to persist campaign %s", cid)
        await _discard_campaign(k, cid)
        raise HTTPException(500, "Failed to persist campaign") from db_error
    logger.info("created campaign %s (geo=%s, offer=%s)", cid, body.geo, body.offer_id)
    return CampaignCreated(
        id=cid,
        name=name,
        domain_id=domain_id,
        group_id=group_id,
        source_id=source_id,
    )


@router.get("/campaigns")
async def list_campaigns(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[CampaignListItem]:
    result = await db.execute(
        select(CampaignRecord).order_by(CampaignRecord.id.desc()).limit(limit)
    )
    rows = result.scalars().all()
    return [
        CampaignListItem(
            id=r.keitaro_id, name=r.name, geo=r.geo, created_at=r.created_at
        )
        for r in rows
    ]
