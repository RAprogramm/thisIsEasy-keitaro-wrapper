"""Integration tests for the campaign editor endpoints."""

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.editor_service import rebalance
from app.models import CampaignRecord, OfferChange, StreamOffer
from tests.conftest import FakeKeitaro, make_offer_stream


def seed_campaign(fake: FakeKeitaro, cid: int = 1000) -> None:
    fake.campaigns[cid] = {"id": cid, "name": "camp"}
    fake.streams[cid] = [
        {"id": 1, "name": "Geo", "schema": "redirect", "offers": []},
        make_offer_stream(2, [{"offer_id": 100, "share": 100, "state": "active"}]),
    ]


def make_stream_offer(
    offer_id: int, *, status: str = "active", pinned: bool = False, share: int = 0
) -> StreamOffer:
    return StreamOffer(
        keitaro_campaign_id=1000,
        stream_id=2,
        offer_id=offer_id,
        status=status,
        pinned=pinned,
        share=share,
    )


def test_rebalance_even() -> None:
    offers = [make_stream_offer(i) for i in range(3)]
    rebalance(offers)
    assert [o.share for o in offers] == [34, 33, 33]


def test_rebalance_empty() -> None:
    assert rebalance([]) == []


def test_rebalance_respects_pinned() -> None:
    offers = [
        make_stream_offer(1, pinned=True, share=25),
        make_stream_offer(2),
        make_stream_offer(3),
    ]
    rebalance(offers)
    assert offers[0].share == 25
    assert offers[1].share + offers[2].share == 75
    assert offers[1].share in (38, 37)


def test_rebalance_pinned_overfill_never_goes_negative() -> None:
    offers = [
        make_stream_offer(1, pinned=True, share=80),
        make_stream_offer(2, pinned=True, share=40),
        make_stream_offer(3),
    ]
    rebalance(offers)
    assert [o.share for o in offers] == [80, 40, 0]


def test_rebalance_removed_gets_zero() -> None:
    offers = [
        make_stream_offer(1, status="active"),
        make_stream_offer(2, status="removed"),
    ]
    rebalance(offers)
    assert offers[1].share == 0
    assert offers[0].share == 100


def test_search_campaigns_by_name(client: TestClient, fake: FakeKeitaro) -> None:
    seed_campaign(fake)
    body = client.get("/api/campaigns/search", params={"q": " CAM "}).json()
    assert [c["id"] for c in body] == [1000]


def test_search_campaigns_empty_query_returns_head(
    client: TestClient, fake: FakeKeitaro
) -> None:
    seed_campaign(fake)
    body = client.get("/api/campaigns/search").json()
    assert [c["id"] for c in body] == [1000]


def test_search_campaigns_by_exact_id(client: TestClient, fake: FakeKeitaro) -> None:
    seed_campaign(fake)
    body = client.get("/api/campaigns/search", params={"q": "1000"}).json()
    assert [c["id"] for c in body] == [1000]


def test_search_campaigns_no_match(client: TestClient, fake: FakeKeitaro) -> None:
    seed_campaign(fake)
    assert client.get("/api/campaigns/search", params={"q": "zzz"}).json() == []


def test_search_campaigns_validates_limit(client: TestClient) -> None:
    assert client.get("/api/campaigns/search", params={"limit": 0}).status_code == 422


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
    assert body["keitaro_url"] == "https://tlgk.host"
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
    shares = [o["share"] for o in body["streams"][1]["offers"]]
    assert sorted(shares) == [50, 50]
    statuses = {o["offer_id"]: o["status"] for o in body["streams"][1]["offers"]}
    assert statuses[200] == "pending_add"
    assert body["streams"][1]["dirty"] is True


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


def test_add_offer_to_redirect_stream_is_rejected(
    client: TestClient, fake: FakeKeitaro
) -> None:
    seed_campaign(fake)
    r = client.post(
        "/api/campaigns/1000/offers", json={"offer_id": 200, "stream_id": 1}
    )
    assert r.status_code == 400


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


def test_remove_offer_marks_pending(client: TestClient, fake: FakeKeitaro) -> None:
    seed_campaign(fake)
    fake.streams[1000][1]["offers"].append(
        {"offer_id": 200, "share": 0, "state": "active"}
    )
    body = client.delete("/api/campaigns/1000/offers/200").json()
    offers = body["streams"][1]["offers"]
    assert {o["offer_id"] for o in offers} == {100, 200}
    removed = next(o for o in offers if o["offer_id"] == 200)
    assert removed["status"] == "pending_remove"
    assert removed["share"] == 0
    kept = next(o for o in offers if o["offer_id"] == 100)
    assert kept["share"] == 100
    assert body["streams"][1]["dirty"] is True


def test_remove_last_offer_is_blocked(client: TestClient, fake: FakeKeitaro) -> None:
    seed_campaign(fake)
    r = client.delete("/api/campaigns/1000/offers/100")
    assert r.status_code == 400


def test_remove_unknown_offer(client: TestClient, fake: FakeKeitaro) -> None:
    seed_campaign(fake)
    r = client.delete("/api/campaigns/1000/offers/200")
    assert r.status_code == 404


def test_push_publishes_pending(client: TestClient, fake: FakeKeitaro) -> None:
    seed_campaign(fake)
    client.post("/api/campaigns/1000/offers", json={"offer_id": 200})
    body = client.post("/api/campaigns/1000/push?stream_id=2").json()
    assert body["streams"][1]["dirty"] is False
    statuses = {o["offer_id"]: o["status"] for o in body["streams"][1]["offers"]}
    assert statuses[200] == "active"
    # Keitaro stream now contains both offers.
    assert len(fake.streams[1000][1]["offers"]) == 2


def test_push_remove_archives(client: TestClient, fake: FakeKeitaro) -> None:
    seed_campaign(fake)
    fake.streams[1000][1]["offers"].append(
        {"offer_id": 200, "share": 0, "state": "active"}
    )
    client.delete("/api/campaigns/1000/offers/200")
    body = client.post("/api/campaigns/1000/push?stream_id=2").json()
    archived = next(o for o in body["streams"][1]["offers"] if o["offer_id"] == 200)
    assert archived["status"] == "removed"
    assert (
        "200" not in [str(o["offer_id"]) for o in fake.streams[1000][1]["offers"]]
        or True
    )
    # Keitaro stream no longer contains 200.
    ids = [o["offer_id"] for o in fake.streams[1000][1]["offers"]]
    assert 200 not in ids


def test_cancel_discards_pending_add(client: TestClient, fake: FakeKeitaro) -> None:
    seed_campaign(fake)
    client.post("/api/campaigns/1000/offers", json={"offer_id": 200})
    body = client.post("/api/campaigns/1000/cancel?stream_id=2").json()
    assert body["streams"][1]["dirty"] is False
    ids = [o["offer_id"] for o in body["streams"][1]["offers"]]
    assert 200 not in ids


def test_cancel_restores_pending_remove(client: TestClient, fake: FakeKeitaro) -> None:
    seed_campaign(fake)
    fake.streams[1000][1]["offers"].append(
        {"offer_id": 200, "share": 0, "state": "active"}
    )
    client.delete("/api/campaigns/1000/offers/200")
    body = client.post("/api/campaigns/1000/cancel?stream_id=2").json()
    target = next(o for o in body["streams"][1]["offers"] if o["offer_id"] == 200)
    assert target["status"] == "active"


def test_restore_archived_offer(client: TestClient, fake: FakeKeitaro) -> None:
    seed_campaign(fake)
    fake.streams[1000][1]["offers"].append(
        {"offer_id": 200, "share": 0, "state": "active"}
    )
    client.delete("/api/campaigns/1000/offers/200")
    client.post("/api/campaigns/1000/push?stream_id=2")
    body = client.post("/api/campaigns/1000/offers/200/restore?stream_id=2").json()
    restored = next(o for o in body["streams"][1]["offers"] if o["offer_id"] == 200)
    assert restored["status"] == "pending_add"
    assert body["streams"][1]["dirty"] is True


def test_restore_non_archived_is_404(client: TestClient, fake: FakeKeitaro) -> None:
    seed_campaign(fake)
    r = client.post("/api/campaigns/1000/offers/100/restore?stream_id=2")
    assert r.status_code == 404


def test_pin_offer(client: TestClient, fake: FakeKeitaro) -> None:
    seed_campaign(fake)
    fake.streams[1000][1]["offers"].append(
        {"offer_id": 200, "share": 0, "state": "active"}
    )
    body = client.post(
        "/api/campaigns/1000/offers/100/pin?stream_id=2&pinned=true"
    ).json()
    pinned = next(o for o in body["streams"][1]["offers"] if o["offer_id"] == 100)
    assert pinned["pinned"] is True
    assert body["streams"][1]["dirty"] is True


def test_pin_unknown_offer_is_404(client: TestClient, fake: FakeKeitaro) -> None:
    seed_campaign(fake)
    r = client.post("/api/campaigns/1000/offers/999/pin?stream_id=2&pinned=true")
    assert r.status_code == 404


def test_pin_pending_remove_offer_is_404(client: TestClient, fake: FakeKeitaro) -> None:
    seed_campaign(fake)
    fake.streams[1000][1]["offers"].append(
        {"offer_id": 200, "share": 0, "state": "active"}
    )
    client.delete("/api/campaigns/1000/offers/200")
    r = client.post("/api/campaigns/1000/offers/200/pin?stream_id=2&pinned=true")
    assert r.status_code == 404


def test_sync_marks_vanished_as_removed(client: TestClient, fake: FakeKeitaro) -> None:
    seed_campaign(fake)
    # Track 200 locally as active.
    client.post("/api/campaigns/1000/offers", json={"offer_id": 200})
    client.post("/api/campaigns/1000/push?stream_id=2")
    # Now remove 200 from Keitaro directly.
    fake.streams[1000][1]["offers"] = [
        o for o in fake.streams[1000][1]["offers"] if o["offer_id"] != 200
    ]
    body = client.get("/api/campaigns/1000").json()
    target = next(o for o in body["streams"][1]["offers"] if o["offer_id"] == 200)
    assert target["status"] == "removed"


def test_push_noop_when_clean(client: TestClient, fake: FakeKeitaro) -> None:
    seed_campaign(fake)
    # No pending changes -> push should not call update_stream.
    before = len(fake.calls)
    r = client.post("/api/campaigns/1000/push?stream_id=2")
    assert r.status_code == 200
    update_calls = [c for c in fake.calls[before:] if c[0] == "update_stream"]
    assert update_calls == []


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
    changes = db.scalars(select(OfferChange)).all()
    assert [(c.offer_id, c.action) for c in changes] == [(200, "remove")]


def test_offer_changes_cancelled_are_unlogged(
    client: TestClient, fake: FakeKeitaro, db: Session
) -> None:
    r = client.post("/api/campaigns", json={"name": "c", "geo": "US", "offer_id": 100})
    cid = r.json()["id"]
    fake.streams[cid] = [
        make_offer_stream(2, [{"offer_id": 100, "share": 100, "state": "active"}])
    ]
    client.post(f"/api/campaigns/{cid}/offers", json={"offer_id": 200})
    assert db.scalars(select(OfferChange)).all()
    client.post(f"/api/campaigns/{cid}/cancel?stream_id=2")
    assert db.scalars(select(OfferChange)).all() == []


def test_changes_of_foreign_campaigns_are_not_logged(
    client: TestClient, fake: FakeKeitaro, db: Session
) -> None:
    seed_campaign(fake)
    fake.streams[1000][1]["offers"].append(
        {"offer_id": 200, "share": 0, "state": "active"}
    )
    client.delete("/api/campaigns/1000/offers/200")
    assert db.scalar(select(func.count()).select_from(CampaignRecord)) == 0
    assert db.scalar(select(func.count()).select_from(OfferChange)) == 0


def test_campaign_cascade_deletes_changes(db: Session) -> None:
    from app.models import CampaignRecord, OfferChange

    record = CampaignRecord(keitaro_id=1, name="n", geo="US", offer_id=1)
    record.changes.append(OfferChange(offer_id=2, action="add"))
    db.add(record)
    db.commit()
    db.delete(record)
    db.commit()
    assert db.scalar(select(func.count()).select_from(OfferChange)) == 0


def test_add_restores_archived_offer(client: TestClient, fake: FakeKeitaro) -> None:
    seed_campaign(fake)
    fake.streams[1000][1]["offers"].append(
        {"offer_id": 200, "share": 0, "state": "active"}
    )
    client.delete("/api/campaigns/1000/offers/200")
    client.post("/api/campaigns/1000/push?stream_id=2")
    body = client.post("/api/campaigns/1000/offers", json={"offer_id": 200}).json()
    restored = next(o for o in body["streams"][1]["offers"] if o["offer_id"] == 200)
    assert restored["status"] == "pending_add"


def test_remove_pending_add_deletes_it(client: TestClient, fake: FakeKeitaro) -> None:
    seed_campaign(fake)
    client.post("/api/campaigns/1000/offers", json={"offer_id": 200})
    body = client.delete("/api/campaigns/1000/offers/200").json()
    ids = [o["offer_id"] for o in body["streams"][1]["offers"]]
    assert 200 not in ids


def test_remove_pending_add_returns_its_share_to_the_stream(
    client: TestClient, fake: FakeKeitaro
) -> None:
    seed_campaign(fake)
    added = client.post("/api/campaigns/1000/offers", json={"offer_id": 200}).json()
    assert [o["share"] for o in added["streams"][1]["offers"]] == [50, 50]
    body = client.delete("/api/campaigns/1000/offers/200").json()
    offers = body["streams"][1]["offers"]
    assert [(o["offer_id"], o["share"]) for o in offers] == [(100, 100)]
    assert body["streams"][1]["dirty"] is False
