import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..keitaro import KeitaroClient, get_client
from ..models import CampaignRecord
from ..schemas import CampaignCreate

router = APIRouter(prefix="/api", tags=["creator"])


def _pick(items: list[dict[str, Any]], wanted: int | None, label: str) -> int:
    if wanted is not None:
        if not any(i["id"] == wanted for i in items):
            raise HTTPException(400, f"{label} с id={wanted} не найден в Keitaro")
        return wanted
    if not items:
        raise HTTPException(400, f"В Keitaro нет ни одного значения для: {label}")
    return int(items[0]["id"])


@router.get("/dictionaries")
def dictionaries(k: KeitaroClient = Depends(get_client)) -> dict[str, Any]:
    """Dictionaries for the form: domains, groups, sources, offers."""
    return {
        "domains": [{"id": d["id"], "name": d["name"]} for d in k.domains()],
        "groups": [{"id": g["id"], "name": g["name"]} for g in k.groups()],
        "sources": [{"id": s["id"], "name": s["name"]} for s in k.traffic_sources()],
        "offers": [{"id": o["id"], "name": o["name"]} for o in k.offers()],
    }


@router.post("/campaigns", status_code=201)
def create_campaign(
    body: CampaignCreate,
    db: Session = Depends(get_db),
    k: KeitaroClient = Depends(get_client),
) -> dict[str, Any]:
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

    campaign = k.create_campaign(
        {
            "name": name,
            "alias": secrets.token_hex(4),
            "type": "position",
            "state": "active",
            "domain_id": domain_id,
            "group_id": group_id,
            "traffic_source_id": source_id,
            "cost_type": "CPC",
            "cost_value": 0,
            "cost_currency": "USD",
        }
    )
    cid = campaign["id"]

    k.create_stream(
        {
            "campaign_id": cid,
            "name": f"{body.geo} -> Google",
            "type": "regular",
            "position": 1,
            "weight": 100,
            "state": "active",
            "collect_clicks": True,
            "schema": "redirect",
            "action_type": "http",
            "action_payload": settings.google_url,
            "filter_or": False,
            "filters": [{"name": "country", "mode": "accept", "payload": [body.geo]}],
        }
    )
    k.create_stream(
        {
            "campaign_id": cid,
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
            "offers": [{"offer_id": body.offer_id, "share": 100, "state": "active"}],
        }
    )

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
    return {
        "id": cid,
        "name": name,
        "domain_id": domain_id,
        "group_id": group_id,
        "source_id": source_id,
    }


@router.get("/campaigns")
def list_campaigns(
    db: Session = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, Any]]:
    rows = (
        db.query(CampaignRecord).order_by(CampaignRecord.id.desc()).limit(limit).all()
    )
    return [
        {
            "id": r.keitaro_id,
            "name": r.name,
            "geo": r.geo,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
