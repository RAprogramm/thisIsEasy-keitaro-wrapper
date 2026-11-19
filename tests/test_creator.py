"""Integration tests for the campaign creator endpoints."""

from fastapi.testclient import TestClient

from tests.conftest import FakeKeitaro


def test_dictionaries(client: TestClient, fake: FakeKeitaro) -> None:
    body = client.get("/api/dictionaries").json()
    assert body["domains"][0]["name"] == "d1.com"
    assert {o["id"] for o in body["offers"]} == {100, 200}
    assert body["sources"][0]["id"] == 20


def test_create_uses_first_dictionary_entries(
    client: TestClient, fake: FakeKeitaro
) -> None:
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


def test_create_keeps_existing_prefix(client: TestClient, fake: FakeKeitaro) -> None:
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


def test_create_rejects_unknown_domain(client: TestClient, fake: FakeKeitaro) -> None:
    r = client.post(
        "/api/campaigns",
        json={"name": "c", "geo": "US", "offer_id": 100, "domain_id": 77},
    )
    assert r.status_code == 400


def test_create_rejects_empty_dictionary(client: TestClient, fake: FakeKeitaro) -> None:
    fake.groups_list = []
    r = client.post("/api/campaigns", json={"name": "c", "geo": "US", "offer_id": 100})
    assert r.status_code == 400


def test_list_campaigns(client: TestClient, fake: FakeKeitaro) -> None:
    client.post("/api/campaigns", json={"name": "c1", "geo": "US", "offer_id": 100})
    rows = client.get("/api/campaigns").json()
    assert len(rows) == 1
    assert rows[0]["geo"] == "US"
    assert rows[0]["name"] == "test_rozanov_c1"


def test_list_campaigns_validates_limit(client: TestClient) -> None:
    assert client.get("/api/campaigns", params={"limit": 0}).status_code == 422
    assert client.get("/api/campaigns", params={"limit": 501}).status_code == 422
