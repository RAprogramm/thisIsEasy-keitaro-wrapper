"""Integration tests for the campaign editor endpoints."""

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import CampaignRecord, OfferChange
from app.routers.editor import _rebalance
from tests.conftest import FakeKeitaro, make_offer_stream


def seed_campaign(fake: FakeKeitaro, cid: int = 1000) -> None:
    fake.campaigns[cid] = {"id": cid, "name": "camp"}
    fake.streams[cid] = [
        {"id": 1, "name": "Geo", "schema": "redirect", "offers": []},
        make_offer_stream(2, [{"offer_id": 100, "share": 100, "state": "active"}]),
    ]


def test_rebalance_even() -> None:
    offers = [{"offer_id": i} for i in range(3)]
    assert [o["share"] for o in _rebalance(offers)] == [34, 33, 33]


def test_rebalance_empty() -> None:
    assert _rebalance([]) == []


def test_get_campaign_merges_stats(client: TestClient, fake: FakeKeitaro) -> None:
    seed_campaign(fake)
    fake.report_rows = [
        {
            "offer_id": 100,
            "clicks": 5,
            "campaign_unique_clicks": 4,
            "conversions": 1,
            "revenue": "10",
            "cost": "2",
            "profit": "8",
        }
    ]
    body = client.get("/api/campaigns/1000").json()
    offer = body["streams"][1]["offers"][0]
    assert offer["name"] == "offer A"
    assert offer["stats"]["clicks"] == 5
    assert offer["stats"]["profit"] == "8"


def test_get_campaign_skips_rows_without_offer_id(
    client: TestClient, fake: FakeKeitaro
) -> None:
    seed_campaign(fake)
    fake.report_rows = [{"offer_id": None, "clicks": 9}]
    body = client.get("/api/campaigns/1000").json()
    assert body["streams"][1]["offers"][0]["stats"]["clicks"] == 0


def test_get_campaign_surfaces_stats_error(
    client: TestClient, fake: FakeKeitaro
) -> None:
    seed_campaign(fake)
    fake.report_error = HTTPException(500, "report down")
    body = client.get("/api/campaigns/1000").json()
    assert "report down" in body["stats_error"]


def test_add_offer_rebalances(client: TestClient, fake: FakeKeitaro) -> None:
    seed_campaign(fake)
    body = client.post("/api/campaigns/1000/offers", json={"offer_id": 200}).json()
    assert [o["share"] for o in body["streams"][1]["offers"]] == [50, 50]


def test_add_offer_into_explicit_stream(client: TestClient, fake: FakeKeitaro) -> None:
    seed_campaign(fake)
    r = client.post(
        "/api/campaigns/1000/offers", json={"offer_id": 200, "stream_id": 2}
    )
    assert r.status_code == 200


def test_add_offer_unknown_stream(client: TestClient, fake: FakeKeitaro) -> None:
    seed_campaign(fake)
    r = client.post(
        "/api/campaigns/1000/offers", json={"offer_id": 200, "stream_id": 99}
    )
    assert r.status_code == 404


def test_add_offer_without_offer_stream(client: TestClient, fake: FakeKeitaro) -> None:
    fake.campaigns[1000] = {"id": 1000, "name": "camp"}
    fake.streams[1000] = [{"id": 1, "name": "r", "schema": "redirect", "offers": []}]
    r = client.post("/api/campaigns/1000/offers", json={"offer_id": 200})
    assert r.status_code == 400


def test_add_offer_unknown_offer(client: TestClient, fake: FakeKeitaro) -> None:
    seed_campaign(fake)
    r = client.post("/api/campaigns/1000/offers", json={"offer_id": 999})
    assert r.status_code == 400


def test_add_duplicate_offer(client: TestClient, fake: FakeKeitaro) -> None:
    seed_campaign(fake)
    r = client.post("/api/campaigns/1000/offers", json={"offer_id": 100})
    assert r.status_code == 409


def test_remove_offer_rebalances(client: TestClient, fake: FakeKeitaro) -> None:
    seed_campaign(fake)
    fake.streams[1000][1]["offers"].append(
        {"offer_id": 200, "share": 0, "state": "active"}
    )
    body = client.delete("/api/campaigns/1000/offers/200").json()
    offers = body["streams"][1]["offers"]
    assert [o["offer_id"] for o in offers] == [100]
    assert offers[0]["share"] == 100


def test_remove_last_offer_is_blocked(client: TestClient, fake: FakeKeitaro) -> None:
    seed_campaign(fake)
    r = client.delete("/api/campaigns/1000/offers/100")
    assert r.status_code == 400


def test_remove_unknown_offer(client: TestClient, fake: FakeKeitaro) -> None:
    seed_campaign(fake)
    r = client.delete("/api/campaigns/1000/offers/200")
    assert r.status_code == 404


def test_offer_changes_are_logged(
    client: TestClient, fake: FakeKeitaro, db: Session
) -> None:
    r = client.post("/api/campaigns", json={"name": "c", "geo": "US", "offer_id": 100})
    cid = r.json()["id"]
    fake.streams[cid] = [
        make_offer_stream(
            2,
            [
                {"offer_id": 100, "share": 50, "state": "active"},
                {"offer_id": 200, "share": 50, "state": "active"},
            ],
        )
    ]
    client.delete(f"/api/campaigns/{cid}/offers/200")
    changes = db.query(OfferChange).all()
    assert [(c.offer_id, c.action) for c in changes] == [(200, "remove")]


def test_changes_of_foreign_campaigns_are_not_logged(
    client: TestClient, fake: FakeKeitaro, db: Session
) -> None:
    seed_campaign(fake)
    fake.streams[1000][1]["offers"].append(
        {"offer_id": 200, "share": 0, "state": "active"}
    )
    client.delete("/api/campaigns/1000/offers/200")
    assert db.query(CampaignRecord).count() == 0
    assert db.query(OfferChange).count() == 0
