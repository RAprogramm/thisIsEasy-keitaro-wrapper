"""Tests for the application entry points and the database session helper."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import get_db


def test_index_serves_the_single_page(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "Keitaro wrapper" in r.text


def test_static_files_are_mounted(client: TestClient) -> None:
    assert client.get("/static/index.html").status_code == 200


def test_get_db_yields_and_closes_a_session() -> None:
    generator = get_db()
    session = next(generator)
    assert session is not None
    with pytest.raises(StopIteration):
        next(generator)


def test_campaign_cascade_deletes_changes(db: Session) -> None:
    from app.models import CampaignRecord, OfferChange

    record = CampaignRecord(keitaro_id=1, name="n", geo="US", offer_id=1)
    record.changes.append(OfferChange(offer_id=2, action="add"))
    db.add(record)
    db.commit()
    db.delete(record)
    db.commit()
    assert db.query(OfferChange).count() == 0
