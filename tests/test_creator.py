"""Integration tests for the campaign creator endpoints."""

import logging

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from tests.conftest import FakeKeitaro


def test_dictionaries(client: TestClient) -> None:
    body = client.get("/api/dictionaries").json()
    assert body["domains"][0]["name"] == "d1.com"
    assert {o["id"] for o in body["offers"]} == {100, 200}
    assert body["sources"][0]["id"] == 20


def test_search_offers_empty_query_returns_head(client: TestClient) -> None:
    body = client.get("/api/offers/search").json()
    assert [o["id"] for o in body] == [100, 200]


def test_search_offers_blank_query_returns_head(client: TestClient) -> None:
    body = client.get("/api/offers/search", params={"q": "   "}).json()
    assert [o["id"] for o in body] == [100, 200]


def test_search_offers_by_name_case_insensitive(client: TestClient) -> None:
    body = client.get("/api/offers/search", params={"q": " OFFER a"}).json()
    assert [o["id"] for o in body] == [100]


def test_search_offers_by_exact_id(client: TestClient, fake: FakeKeitaro) -> None:
    fake.offers_list.append({"id": 7, "name": "lucky seven"})
    body = client.get("/api/offers/search", params={"q": "7"}).json()
    assert [o["id"] for o in body] == [7]


def test_search_offers_numeric_without_id_falls_back_to_name(
    client: TestClient, fake: FakeKeitaro
) -> None:
    fake.offers_list.append({"id": 55, "name": "deal 999"})
    body = client.get("/api/offers/search", params={"q": "999"}).json()
    assert [o["id"] for o in body] == [55]


def test_search_offers_no_match(client: TestClient) -> None:
    assert client.get("/api/offers/search", params={"q": "zzz"}).json() == []


def test_search_offers_respects_limit(client: TestClient) -> None:
    body = client.get("/api/offers/search", params={"limit": 1}).json()
    assert len(body) == 1


def test_search_offers_validates_params(client: TestClient) -> None:
    assert client.get("/api/offers/search", params={"limit": 0}).status_code == 422
    assert client.get("/api/offers/search", params={"q": "x" * 101}).status_code == 422


def test_create_uses_first_dictionary_entries(client: TestClient) -> None:
    r = client.post("/api/campaigns", json={"name": "c1", "geo": "de", "offer_id": 100})
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "c1"
    assert (body["domain_id"], body["group_id"], body["source_id"]) == (1, 10, 20)


def test_create_builds_two_streams(client: TestClient, fake: FakeKeitaro) -> None:
    client.post("/api/campaigns", json={"name": "c1", "geo": "DE", "offer_id": 100})
    streams = [c[1]["payload"] for c in fake.calls if c[0] == "create_stream"]
    assert len(streams) == 2
    geo_stream, offer_stream = streams
    assert geo_stream["filters"] == [
        {"name": "country", "mode": "accept", "payload": ["DE"]}
    ]
    assert geo_stream["schema"] == "redirect"
    assert geo_stream["action_payload"] == "https://www.google.com"
    assert offer_stream["filters"] == []
    assert offer_stream["schema"] == "landings"
    assert offer_stream["offers"] == [
        {"offer_id": 100, "share": 100, "state": "active"}
    ]


def test_create_accepts_comma_separated_geos(
    client: TestClient, fake: FakeKeitaro
) -> None:
    r = client.post(
        "/api/campaigns", json={"name": "c1", "geo": "mx, au ,ro", "offer_id": 100}
    )
    assert r.status_code == 201
    assert r.json()["name"] == "c1"
    streams = [c[1]["payload"] for c in fake.calls if c[0] == "create_stream"]
    assert streams[0]["filters"] == [
        {"name": "country", "mode": "accept", "payload": ["MX", "AU", "RO"]}
    ]


def test_create_rejects_bad_geo_codes(client: TestClient) -> None:
    for bad in ("USA", "XX", "1,2", ",,"):
        r = client.post(
            "/api/campaigns", json={"name": "c", "geo": bad, "offer_id": 100}
        )
        assert r.status_code == 422, bad


def test_countries_endpoint_lists_codes(client: TestClient) -> None:
    r = client.get("/api/countries")
    assert r.status_code == 200
    codes = r.json()
    assert "AU" in codes and "DE" in codes
    assert codes == sorted(codes)


def test_create_sends_the_name_verbatim(client: TestClient) -> None:
    r = client.post(
        "/api/campaigns",
        json={"name": "test_rozanov_pre", "geo": "US", "offer_id": 100, "domain_id": 2},
    )
    assert r.json()["name"] == "test_rozanov_pre"
    assert r.json()["domain_id"] == 2


def test_create_rejects_unknown_offer(client: TestClient, fake: FakeKeitaro) -> None:
    r = client.post("/api/campaigns", json={"name": "c", "geo": "US", "offer_id": 999})
    assert r.status_code == 400
    assert not any(c[0] == "create_campaign" for c in fake.calls)


def test_create_rejects_unknown_domain(client: TestClient) -> None:
    r = client.post(
        "/api/campaigns",
        json={"name": "c", "geo": "US", "offer_id": 100, "domain_id": 77},
    )
    assert r.status_code == 400


def test_create_rejects_empty_dictionary(client: TestClient, fake: FakeKeitaro) -> None:
    fake.groups_list = []
    r = client.post("/api/campaigns", json={"name": "c", "geo": "US", "offer_id": 100})
    assert r.status_code == 400


def test_list_campaigns(client: TestClient) -> None:
    client.post("/api/campaigns", json={"name": "c1", "geo": "US", "offer_id": 100})
    rows = client.get("/api/campaigns").json()
    assert len(rows) == 1
    assert rows[0]["geo"] == "US"
    assert rows[0]["name"] == "c1"


def test_list_campaigns_validates_limit(client: TestClient) -> None:
    assert client.get("/api/campaigns", params={"limit": 0}).status_code == 422
    assert client.get("/api/campaigns", params={"limit": 501}).status_code == 422


def test_alias_collision_is_retried(client: TestClient, fake: FakeKeitaro) -> None:
    fake.create_campaign_failures = [
        HTTPException(400, "Keitaro: alias X already used")
    ]
    r = client.post("/api/campaigns", json={"name": "c1", "geo": "US", "offer_id": 100})
    assert r.status_code == 201
    assert sum(c[0] == "create_campaign" for c in fake.calls) == 2


def test_alias_retries_are_exhausted(client: TestClient, fake: FakeKeitaro) -> None:
    fake.create_campaign_failures = [HTTPException(400, "alias X used")] * 3
    r = client.post("/api/campaigns", json={"name": "c1", "geo": "US", "offer_id": 100})
    assert r.status_code == 400
    assert sum(c[0] == "create_campaign" for c in fake.calls) == 3


def test_non_alias_error_is_not_retried(client: TestClient, fake: FakeKeitaro) -> None:
    fake.create_campaign_failures = [HTTPException(400, "name is required")]
    r = client.post("/api/campaigns", json={"name": "c1", "geo": "US", "offer_id": 100})
    assert r.status_code == 400
    assert sum(c[0] == "create_campaign" for c in fake.calls) == 1


def test_stream_failure_deletes_the_campaign(
    client: TestClient, fake: FakeKeitaro
) -> None:
    fake.create_stream_failures = [HTTPException(502, "boom")]
    r = client.post("/api/campaigns", json={"name": "c1", "geo": "US", "offer_id": 100})
    assert r.status_code == 502
    assert fake.deleted_campaigns == [1000]


def test_cleanup_failure_keeps_the_original_error(
    client: TestClient, fake: FakeKeitaro, caplog: pytest.LogCaptureFixture
) -> None:
    fake.create_stream_failures = [HTTPException(502, "boom")]
    fake.delete_campaign_failures = [HTTPException(404, "gone")]
    with caplog.at_level(logging.WARNING, logger="app.routers.creator"):
        r = client.post(
            "/api/campaigns", json={"name": "c1", "geo": "US", "offer_id": 100}
        )
    assert r.status_code == 502
    assert "cleanup failed" in caplog.text


def test_idempotency_key_returns_existing_campaign(
    client: TestClient, fake: FakeKeitaro
) -> None:
    headers = {"Idempotency-Key": "key-1"}
    r1 = client.post(
        "/api/campaigns",
        json={"name": "c1", "geo": "US", "offer_id": 100},
        headers=headers,
    )
    assert r1.status_code == 201
    cid = r1.json()["id"]
    # second call with same key must not create a new campaign
    r2 = client.post(
        "/api/campaigns",
        json={"name": "c2", "geo": "DE", "offer_id": 200},
        headers=headers,
    )
    assert r2.status_code == 201
    assert r2.json()["id"] == cid
    assert len(fake.campaigns) == 1


def test_create_compensates_on_db_failure(
    client: TestClient, fake: FakeKeitaro
) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    from tests.conftest import AsyncTestSession

    class BoomSession(AsyncSession):
        async def commit(self) -> None:
            raise RuntimeError("db down")

    async def override_db() -> object:
        real = AsyncTestSession()
        session = BoomSession(bind=real.bind)
        try:
            yield session
        finally:
            await session.close()

    from app.db import get_db
    from app.main import app as fastapi_app

    fake.delete_campaign_failures.append(HTTPException(404, "gone"))
    fastapi_app.dependency_overrides[get_db] = override_db
    try:
        r = client.post(
            "/api/campaigns", json={"name": "c1", "geo": "US", "offer_id": 100}
        )
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)
    assert r.status_code == 500
