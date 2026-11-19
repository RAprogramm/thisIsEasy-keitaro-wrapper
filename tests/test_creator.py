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


def test_create_uses_first_dictionary_entries(client: TestClient) -> None:
    r = client.post("/api/campaigns", json={"name": "c1", "geo": "de", "offer_id": 100})
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "test_rozanov_c1"
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


def test_create_keeps_existing_prefix(client: TestClient) -> None:
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
    assert rows[0]["name"] == "test_rozanov_c1"


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
    from tests.conftest import TestSession

    class BoomSession:
        def __init__(self, real: object) -> None:
            self._real = real

        def add(self, obj: object) -> None:
            self._real.add(obj)  # type: ignore[attr-defined]

        def commit(self) -> None:
            raise RuntimeError("db down")

        def rollback(self) -> None:
            self._real.rollback()  # type: ignore[attr-defined]

        def close(self) -> None:
            self._real.close()  # type: ignore[attr-defined]

        def __getattr__(self, name: str) -> object:
            return getattr(self._real, name)

    def override_db() -> object:
        real = TestSession()
        yield BoomSession(real)

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
