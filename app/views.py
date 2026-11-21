"""Assembly of the editor's campaign payload from Keitaro and local state."""

from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .errors import UpstreamError
from .keitaro import LANDINGS_SCHEMA, KeitaroClient
from .schemas import CampaignView, OfferStats, OfferView, StreamView
from .shares import ACTIVE_STATUSES, is_dirty
from .sync import local_offers, sync_stream


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
    except UpstreamError as e:
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
        alias=str(campaign.get("alias", "")),
        streams=result_streams,
        stats_error=stats_error,
        keitaro_url=settings.keitaro_url,
    )
