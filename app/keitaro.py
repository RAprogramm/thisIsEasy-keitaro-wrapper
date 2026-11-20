"""Thin client for the Keitaro Admin API v1 (Api-Key header)."""

import asyncio
import logging
import random
import threading
from collections.abc import Callable
from typing import Any, ClassVar, TypedDict, cast

import httpx2
from fastapi import HTTPException

from .config import settings

logger = logging.getLogger(__name__)

LANDINGS_SCHEMA = "landings"


class KeitaroDomain(TypedDict):
    """A Keitaro domain dictionary entry."""

    id: int
    name: str


class KeitaroGroup(TypedDict):
    """A Keitaro group dictionary entry."""

    id: int
    name: str


class KeitaroSource(TypedDict):
    """A Keitaro traffic source dictionary entry."""

    id: int
    name: str


class KeitaroOffer(TypedDict):
    """A Keitaro offer dictionary entry."""

    id: int
    name: str


class KeitaroCampaign(TypedDict, total=False):
    """A Keitaro campaign as returned by the API."""

    id: int
    name: str
    type: str
    state: str
    domain_id: int
    group_id: int
    traffic_source_id: int


class KeitaroStreamOffer(TypedDict, total=False):
    """An offer inside a Keitaro stream."""

    offer_id: int
    share: int
    state: str


class KeitaroStream(TypedDict, total=False):
    """A Keitaro stream as returned by the API."""

    id: int
    name: str
    type: str
    position: int
    weight: int
    state: str
    schema: str
    action_type: str
    action_payload: str
    filters: list[dict[str, Any]]
    offers: list[KeitaroStreamOffer]


class KeitaroClient:
    """Async client over the Keitaro Admin API v1.

    Wraps a persistent ``httpx2.AsyncClient`` so connections are reused between calls.
    """

    def __init__(self, base_url: str | None = None, api_key: str | None = None) -> None:
        self.base = (base_url or settings.keitaro_url).rstrip("/") + "/admin_api/v1"
        self.headers = {
            "Api-Key": (api_key or settings.keitaro_api_key.get_secret_value())
        }
        self._sleep: Callable[[float], Any] = asyncio.sleep
        self.MAX_ATTEMPTS = 3
        self._client = httpx2.AsyncClient(
            base_url=self.base,
            headers=self.headers,
            timeout=settings.keitaro_timeout,
        )

    RETRYABLE_STATUSES: ClassVar[frozenset[int]] = frozenset({429, 502, 503, 504})

    @staticmethod
    def _error_detail(r: httpx2.Response) -> str:
        """Summarize an upstream failure for the client.

        Keitaro itself answers with JSON errors, which are passed through.
        Proxies in front of it answer with HTML pages, which would flood the
        UI, so they collapse to the status line.
        """
        body = r.text.strip()
        if not body or body.startswith("<"):
            return f"Keitaro: HTTP {r.status_code}"
        return f"Keitaro: {body[:500]}"

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            try:
                r = await self._client.request(method, path, **kwargs)
            except httpx2.HTTPError as e:
                last_error = e
                if attempt == self.MAX_ATTEMPTS:
                    logger.warning("Keitaro unreachable: %s %s: %s", method, path, e)
                    raise HTTPException(502, f"Keitaro недоступен: {e}") from e
                await self._sleep_backoff(attempt, None)
                continue
            if r.status_code in self.RETRYABLE_STATUSES:
                last_error = HTTPException(r.status_code, self._error_detail(r))
                if attempt == self.MAX_ATTEMPTS:
                    logger.warning(
                        "Keitaro rejected %s %s with %d: %s",
                        method,
                        path,
                        r.status_code,
                        r.text[:200],
                    )
                    raise HTTPException(r.status_code, self._error_detail(r))
                retry_after = r.headers.get("Retry-After")
                await self._sleep_backoff(attempt, retry_after)
                continue
            if r.status_code >= 400:
                logger.warning(
                    "Keitaro rejected %s %s with %d: %s",
                    method,
                    path,
                    r.status_code,
                    r.text[:200],
                )
                raise HTTPException(r.status_code, self._error_detail(r))
            return r.json() if r.content else None
        raise HTTPException(
            502, "Keitaro недоступен"
        ) from last_error  # pragma: no cover

    async def _sleep_backoff(self, attempt: int, retry_after: str | None) -> None:
        if retry_after is not None:
            try:
                delay = float(retry_after)
            except ValueError:
                delay = 0.0
            result = self._sleep(min(delay, 5.0))
            if asyncio.iscoroutine(result):  # pragma: no cover
                await result  # pragma: no cover
            return
        delay = min(2 ** (attempt - 1), 4) + random.uniform(0, 0.25)  # noqa: S311
        result = self._sleep(delay)
        if asyncio.iscoroutine(result):
            await result

    # --- dictionaries ---
    async def domains(self) -> list[KeitaroDomain]:
        return cast(list[KeitaroDomain], await self._request("GET", "/domains"))

    async def groups(self) -> list[KeitaroGroup]:
        return cast(
            list[KeitaroGroup],
            await self._request("GET", "/groups", params={"type": "campaigns"}),
        )

    async def traffic_sources(self) -> list[KeitaroSource]:
        return cast(list[KeitaroSource], await self._request("GET", "/traffic_sources"))

    async def offers(self) -> list[KeitaroOffer]:
        return cast(list[KeitaroOffer], await self._request("GET", "/offers"))

    async def get_offer(self, offer_id: int) -> KeitaroOffer | None:
        """Fetch one offer by id; ``None`` when Keitaro reports it missing.

        Preferred over scanning the full ``offers()`` list: one small request
        regardless of how many offers the tracker holds.
        """
        try:
            return cast(KeitaroOffer, await self._request("GET", f"/offers/{offer_id}"))
        except HTTPException as e:
            if e.status_code == 404:
                return None
            raise

    # --- campaigns and streams ---
    async def create_campaign(self, payload: dict[str, Any]) -> KeitaroCampaign:
        return cast(
            KeitaroCampaign, await self._request("POST", "/campaigns", json=payload)
        )

    async def get_campaign(self, campaign_id: int) -> KeitaroCampaign:
        return cast(
            KeitaroCampaign, await self._request("GET", f"/campaigns/{campaign_id}")
        )

    async def all_campaigns(self) -> list[KeitaroCampaign]:
        """All campaigns currently in Keitaro, for the editor picker."""
        return cast(list[KeitaroCampaign], await self._request("GET", "/campaigns"))

    async def delete_campaign(self, campaign_id: int) -> KeitaroCampaign | None:
        return cast(
            KeitaroCampaign, await self._request("DELETE", f"/campaigns/{campaign_id}")
        )

    async def campaign_streams(self, campaign_id: int) -> list[KeitaroStream]:
        return cast(
            list[KeitaroStream],
            await self._request("GET", f"/campaigns/{campaign_id}/streams"),
        )

    async def create_stream(self, payload: dict[str, Any]) -> KeitaroStream:
        return cast(
            KeitaroStream, await self._request("POST", "/streams", json=payload)
        )

    async def update_stream(
        self, stream_id: int, payload: dict[str, Any]
    ) -> KeitaroStream:
        return cast(
            KeitaroStream,
            await self._request("PUT", f"/streams/{stream_id}", json=payload),
        )

    # --- statistics ---
    async def report(
        self,
        campaign_id: int,
        grouping: list[str],
        interval: str = "all_time",
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        if date_from or date_to:
            rng: dict[str, Any] = {}
            if date_from:
                rng["from"] = date_from
            if date_to:
                rng["to"] = date_to
        else:
            rng = {"interval": interval}
        body = {
            "range": rng,
            "dimensions": grouping,
            "measures": [
                "clicks",
                "campaign_unique_clicks",
                "conversions",
                "revenue",
                "cost",
                "profit",
            ],
            "filters": [
                {"name": "campaign_id", "operator": "EQUALS", "expression": campaign_id}
            ],
        }
        return cast(
            dict[str, Any], await self._request("POST", "/report/build", json=body)
        )

    async def close(self) -> None:
        """Release the underlying connection pool."""
        await self._client.aclose()


_client: KeitaroClient | None = None
_client_lock = threading.Lock()


def get_client() -> KeitaroClient:
    """Return the process-wide client so its connection pool is shared."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = KeitaroClient()
    return _client


async def close_client() -> None:
    """Close the shared client if it exists; safe to call more than once."""
    global _client
    with _client_lock:
        if _client is not None:
            await _client.close()
            _client = None


async def ensure_offer_exists(k: KeitaroClient, offer_id: int) -> None:
    """Raise 400 unless Keitaro knows this offer.

    Args:
        k: the Keitaro client to ask.
        offer_id: offer id referenced by the request body.
    """
    if await k.get_offer(offer_id) is None:
        raise HTTPException(400, f"Оффер {offer_id} не найден в Keitaro")
