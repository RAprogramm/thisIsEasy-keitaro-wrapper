"""Thin client for the Keitaro Admin API v1 (Api-Key header)."""

import logging
import random
import threading
import time
from typing import Any, ClassVar, TypedDict, cast

import httpx
from fastapi import HTTPException

from .config import settings

logger = logging.getLogger(__name__)


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
    """Minimal synchronous client over the Keitaro Admin API v1.

    Wraps a persistent ``httpx.Client`` so connections are reused between calls.
    """

    def __init__(self, base_url: str | None = None, api_key: str | None = None) -> None:
        self.base = (base_url or settings.keitaro_url).rstrip("/") + "/admin_api/v1"
        self.headers = {
            "Api-Key": (api_key or settings.keitaro_api_key.get_secret_value())
        }
        self._sleep = time.sleep
        self._client = httpx.Client(
            base_url=self.base,
            headers=self.headers,
            timeout=settings.keitaro_timeout,
        )

    RETRYABLE_STATUSES: ClassVar[frozenset[int]] = frozenset({429, 502, 503, 504})
    MAX_ATTEMPTS: ClassVar[int] = 3

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            try:
                r = self._client.request(method, path, **kwargs)
            except httpx.HTTPError as e:
                last_error = e
                if attempt == self.MAX_ATTEMPTS:
                    logger.warning("Keitaro unreachable: %s %s: %s", method, path, e)
                    raise HTTPException(502, f"Keitaro недоступен: {e}") from e
                self._sleep_backoff(attempt, None)
                continue
            if r.status_code in self.RETRYABLE_STATUSES:
                last_error = HTTPException(r.status_code, f"Keitaro: {r.text[:500]}")
                if attempt == self.MAX_ATTEMPTS:
                    logger.warning(
                        "Keitaro rejected %s %s with %d: %s",
                        method,
                        path,
                        r.status_code,
                        r.text[:200],
                    )
                    raise HTTPException(r.status_code, f"Keitaro: {r.text[:500]}")
                retry_after = r.headers.get("Retry-After")
                self._sleep_backoff(attempt, retry_after)
                continue
            if r.status_code >= 400:
                logger.warning(
                    "Keitaro rejected %s %s with %d: %s",
                    method,
                    path,
                    r.status_code,
                    r.text[:200],
                )
                raise HTTPException(r.status_code, f"Keitaro: {r.text[:500]}")
            return r.json() if r.content else None
        raise HTTPException(502, "Keitaro недоступен") from last_error

    def _sleep_backoff(self, attempt: int, retry_after: str | None) -> None:
        if retry_after is not None:
            try:
                delay = float(retry_after)
            except ValueError:
                delay = 0.0
            self._sleep(min(delay, 5.0))
            return
        delay = min(2 ** (attempt - 1), 4) + random.uniform(0, 0.25)  # noqa: S311
        self._sleep(delay)

    # --- dictionaries ---
    def domains(self) -> list[KeitaroDomain]:
        return cast(list[KeitaroDomain], self._request("GET", "/domains"))

    def groups(self) -> list[KeitaroGroup]:
        return cast(
            list[KeitaroGroup],
            self._request("GET", "/groups", params={"type": "campaigns"}),
        )

    def traffic_sources(self) -> list[KeitaroSource]:
        return cast(list[KeitaroSource], self._request("GET", "/traffic_sources"))

    def offers(self) -> list[KeitaroOffer]:
        return cast(list[KeitaroOffer], self._request("GET", "/offers"))

    # --- campaigns and streams ---
    def create_campaign(self, payload: dict[str, Any]) -> KeitaroCampaign:
        return cast(KeitaroCampaign, self._request("POST", "/campaigns", json=payload))

    def get_campaign(self, campaign_id: int) -> KeitaroCampaign:
        return cast(KeitaroCampaign, self._request("GET", f"/campaigns/{campaign_id}"))

    def delete_campaign(self, campaign_id: int) -> KeitaroCampaign | None:
        return cast(
            KeitaroCampaign, self._request("DELETE", f"/campaigns/{campaign_id}")
        )

    def campaign_streams(self, campaign_id: int) -> list[KeitaroStream]:
        return cast(
            list[KeitaroStream],
            self._request("GET", f"/campaigns/{campaign_id}/streams"),
        )

    def create_stream(self, payload: dict[str, Any]) -> KeitaroStream:
        return cast(KeitaroStream, self._request("POST", "/streams", json=payload))

    def update_stream(self, stream_id: int, payload: dict[str, Any]) -> KeitaroStream:
        return cast(
            KeitaroStream, self._request("PUT", f"/streams/{stream_id}", json=payload)
        )

    # --- statistics ---
    def report(
        self, campaign_id: int, grouping: list[str], interval: str
    ) -> dict[str, Any]:
        body = {
            "range": {"interval": interval},
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
        return cast(dict[str, Any], self._request("POST", "/report/build", json=body))

    def close(self) -> None:
        """Release the underlying connection pool."""
        self._client.close()


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


def close_client() -> None:
    """Close the shared client if it exists; safe to call more than once."""
    global _client
    with _client_lock:
        if _client is not None:
            _client.close()
            _client = None
