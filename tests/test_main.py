"""Tests for the application entry points and the database session helper."""

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db


def test_index_serves_the_single_page(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "Keitaro wrapper" in r.text


def test_healthz_reports_ok(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_static_files_are_mounted(client: TestClient) -> None:
    assert client.get("/static/index.html").status_code == 200


@pytest.mark.anyio
async def test_get_db_yields_and_closes_a_session() -> None:
    agen = get_db()
    session = await agen.__anext__()
    assert session is not None
    with pytest.raises(StopAsyncIteration):
        await agen.__anext__()


@pytest.mark.anyio
async def test_get_db_rolls_back_when_the_request_fails() -> None:
    agen = get_db()
    await agen.__anext__()
    with pytest.raises(RuntimeError, match="boom"):
        await agen.athrow(RuntimeError("boom"))


def test_campaign_cascade_deletes_changes(db: Session) -> None:
    from app.models import CampaignRecord, OfferChange

    record = CampaignRecord(keitaro_id=1, name="n", geo="US", offer_id=1)
    record.changes.append(OfferChange(offer_id=2, action="add"))
    db.add(record)
    db.commit()
    db.delete(record)
    db.commit()
    assert db.scalar(select(func.count()).select_from(OfferChange)) == 0


def test_rate_limit_returns_429(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "rate_limit_per_minute", 1)
    # reset bucket
    from app.main import _rate_limit_state

    _rate_limit_state.clear()
    r1 = client.post("/api/campaigns", json={"name": "c", "geo": "US", "offer_id": 100})
    assert r1.status_code in (201, 400)
    r2 = client.post("/api/campaigns", json={"name": "c", "geo": "US", "offer_id": 100})
    assert r2.status_code == 429
    assert r2.headers.get("X-Request-ID"), "429 must still carry the request id"


def test_rate_limit_evicts_stale_buckets(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    from app.config import settings
    from app.main import _rate_limit_state

    monkeypatch.setattr(settings, "rate_limit_per_minute", 1000)
    _rate_limit_state.clear()
    stale_at = time.monotonic() - 120.0
    for index in range(1001):
        _rate_limit_state[f"stale-{index}"] = [stale_at]
    r = client.post("/api/campaigns", json={"name": "c", "geo": "US", "offer_id": 100})
    assert r.status_code in (201, 400)
    assert len(_rate_limit_state) == 1
    assert all(not ip.startswith("stale-") for ip in _rate_limit_state)


def test_readyz_returns_ok(client: TestClient) -> None:
    r = client.get("/readyz")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"
