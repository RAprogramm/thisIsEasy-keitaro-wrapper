"""Shared fixtures: a fake Keitaro client, a test database, and a TestClient."""

import os
from collections.abc import AsyncGenerator, Iterator
from typing import Any

os.environ.setdefault("TEST_DATABASE_URL", "postgresql+psycopg:///keitaro_test")
os.environ.setdefault("KEITARO_API_KEY", "test-key")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from app import models  # noqa: F401  (registers the tables on Base)
from app.cache import TtlCache
from app.db import Base, get_db
from app.errors import UpstreamError
from app.keitaro import get_client
from app.main import app
from app.routers import creator as creator_router
from app.routers import editor as editor_router

TEST_DB_URL = os.environ["TEST_DATABASE_URL"]

async_engine = create_async_engine(TEST_DB_URL)
AsyncTestSession = async_sessionmaker(
    bind=async_engine, autoflush=False, autocommit=False, expire_on_commit=False
)

engine = create_engine(TEST_DB_URL)
TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture(scope="session", autouse=True)
def _create_schema() -> Iterator[None]:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def _clean_tables() -> Iterator[None]:
    yield
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


@pytest.fixture(autouse=True)
def _reset_dictionaries_cache() -> Iterator[None]:
    creator_router._dictionaries_cache = TtlCache(ttl=60.0)
    editor_router._campaigns_cache = TtlCache(ttl=60.0)
    yield


@pytest.fixture
def db() -> Iterator[Session]:
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


class FakeKeitaro:
    """In-memory stand-in for KeitaroClient; records every call for assertions."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.domains_list: list[dict[str, Any]] = [
            {"id": 1, "name": "d1.com"},
            {"id": 2, "name": "d2.com"},
        ]
        self.groups_list: list[dict[str, Any]] = [{"id": 10, "name": "g1"}]
        self.sources_list: list[dict[str, Any]] = [{"id": 20, "name": "s1"}]
        self.offers_list: list[dict[str, Any]] = [
            {"id": 100, "name": "offer A"},
            {"id": 200, "name": "offer B"},
        ]
        self.campaigns: dict[int, dict[str, Any]] = {}
        self.streams: dict[int, list[dict[str, Any]]] = {}
        self.report_rows: list[dict[str, Any]] = []
        self.report_error: Exception | None = None
        self.create_campaign_failures: list[UpstreamError] = []
        self.create_stream_failures: list[Exception] = []
        self.delete_campaign_failures: list[UpstreamError] = []
        self.deleted_campaigns: list[int] = []
        self._next_id = 1000

    def _record(self, name: str, **kwargs: Any) -> None:
        self.calls.append((name, kwargs))

    async def domains(self) -> list[dict[str, Any]]:
        self._record("domains")
        return self.domains_list

    async def groups(self) -> list[dict[str, Any]]:
        self._record("groups")
        return self.groups_list

    async def traffic_sources(self) -> list[dict[str, Any]]:
        self._record("traffic_sources")
        return self.sources_list

    async def offers(self) -> list[dict[str, Any]]:
        self._record("offers")
        return self.offers_list

    async def get_offer(self, offer_id: int) -> dict[str, Any] | None:
        self._record("get_offer", offer_id=offer_id)
        return next((o for o in self.offers_list if o["id"] == offer_id), None)

    async def create_campaign(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._record("create_campaign", payload=payload)
        if self.create_campaign_failures:
            raise self.create_campaign_failures.pop(0)
        cid = self._next_id
        self._next_id += 1
        campaign = {"id": cid, **payload}
        self.campaigns[cid] = campaign
        return campaign

    async def delete_campaign(self, campaign_id: int) -> dict[str, Any] | None:
        self._record("delete_campaign", campaign_id=campaign_id)
        if self.delete_campaign_failures:
            raise self.delete_campaign_failures.pop(0)
        self.deleted_campaigns.append(campaign_id)
        return self.campaigns.pop(campaign_id, None)

    async def get_campaign(self, campaign_id: int) -> dict[str, Any]:
        self._record("get_campaign", campaign_id=campaign_id)
        return self.campaigns[campaign_id]

    async def all_campaigns(self) -> list[dict[str, Any]]:
        self._record("all_campaigns")
        return list(self.campaigns.values())

    async def campaign_streams(self, campaign_id: int) -> list[dict[str, Any]]:
        self._record("campaign_streams", campaign_id=campaign_id)
        return self.streams.get(campaign_id, [])

    async def create_stream(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._record("create_stream", payload=payload)
        if self.create_stream_failures:
            raise self.create_stream_failures.pop(0)
        sid = self._next_id
        self._next_id += 1
        stream = {"id": sid, **payload}
        self.streams.setdefault(payload["campaign_id"], []).append(stream)
        return stream

    async def update_stream(
        self, stream_id: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        self._record("update_stream", stream_id=stream_id, payload=payload)
        for stream in self.streams.values():
            for existing in stream:
                if existing["id"] == stream_id:
                    existing.update(payload)
                    return existing
        raise AssertionError("stream not found")

    async def report(
        self,
        campaign_id: int,
        grouping: list[str],
        interval: str = "all_time",
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        self._record(
            "report", campaign_id=campaign_id, grouping=grouping, interval=interval
        )
        if self.report_error is not None:
            raise self.report_error
        return {"rows": self.report_rows, "total": len(self.report_rows)}


@pytest.fixture
def fake() -> FakeKeitaro:
    return FakeKeitaro()


@pytest.fixture
def client(fake: FakeKeitaro) -> Iterator[TestClient]:
    async def _override_db() -> AsyncGenerator[AsyncSession]:
        session = AsyncTestSession()
        try:
            yield session
        finally:
            await session.close()

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_client] = lambda: fake
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def make_offer_stream(stream_id: int, offers: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": stream_id, "name": "Offer", "schema": "landings", "offers": offers}
