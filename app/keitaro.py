"""Thin client for the Keitaro Admin API v1 (Api-Key header)."""

import logging
from typing import Any

import httpx
from fastapi import HTTPException

from .config import settings

logger = logging.getLogger(__name__)


class KeitaroClient:
    """Minimal synchronous client over the Keitaro Admin API v1.

    Wraps a persistent ``httpx.Client`` so connections are reused between calls.
    """

    def __init__(self, base_url: str | None = None, api_key: str | None = None) -> None:
        self.base = (base_url or settings.keitaro_url).rstrip("/") + "/admin_api/v1"
        self.headers = {"Api-Key": api_key or settings.keitaro_api_key}
        self._client = httpx.Client(
            base_url=self.base,
            headers=self.headers,
            timeout=settings.keitaro_timeout,
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            r = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as e:
            logger.warning("Keitaro unreachable: %s %s: %s", method, path, e)
            raise HTTPException(502, f"Keitaro недоступен: {e}") from e
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

    # --- dictionaries ---
    def domains(self) -> Any:
        return self._request("GET", "/domains")

    def groups(self) -> Any:
        return self._request("GET", "/groups", params={"type": "campaigns"})

    def traffic_sources(self) -> Any:
        return self._request("GET", "/traffic_sources")

    def offers(self) -> Any:
        return self._request("GET", "/offers")

    # --- campaigns and streams ---
    def create_campaign(self, payload: dict[str, Any]) -> Any:
        return self._request("POST", "/campaigns", json=payload)

    def get_campaign(self, campaign_id: int) -> Any:
        return self._request("GET", f"/campaigns/{campaign_id}")

    def delete_campaign(self, campaign_id: int) -> Any:
        return self._request("DELETE", f"/campaigns/{campaign_id}")

    def campaign_streams(self, campaign_id: int) -> Any:
        return self._request("GET", f"/campaigns/{campaign_id}/streams")

    def create_stream(self, payload: dict[str, Any]) -> Any:
        return self._request("POST", "/streams", json=payload)

    def update_stream(self, stream_id: int, payload: dict[str, Any]) -> Any:
        return self._request("PUT", f"/streams/{stream_id}", json=payload)

    # --- statistics ---
    def report(self, campaign_id: int, grouping: list[str], interval: str) -> Any:
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
        return self._request("POST", "/report/build", json=body)

    def close(self) -> None:
        """Release the underlying connection pool."""
        self._client.close()


_client: KeitaroClient | None = None


def get_client() -> KeitaroClient:
    """Return the process-wide client so its connection pool is shared."""
    global _client
    if _client is None:
        _client = KeitaroClient()
    return _client


def close_client() -> None:
    """Close the shared client if it exists; safe to call more than once."""
    global _client
    if _client is not None:
        _client.close()
        _client = None
