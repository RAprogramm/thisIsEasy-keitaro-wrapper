"""Tests for the Keitaro HTTP client.

All traffic is mocked by respx at the ``httpcore2`` transport level through the
``httpx2_mock`` fixture registered by the ``pytest-httpx2`` plugin.
"""

import json
import logging

import httpx2
import pytest
import respx
from fastapi import HTTPException

from app.keitaro import KeitaroClient, close_client, get_client

BASE = "https://k.test/admin_api/v1"


@pytest.fixture
def kc() -> KeitaroClient:
    return KeitaroClient(base_url="https://k.test", api_key="k")


@pytest.mark.anyio
async def test_default_client_uses_settings() -> None:
    client = get_client()
    assert client.base.endswith("/admin_api/v1")
    assert client.headers["Api-Key"]
    assert get_client() is client


@pytest.mark.anyio
async def test_close_client_releases_and_resets_singleton() -> None:
    client = get_client()
    await close_client()
    assert client._client.is_closed
    assert get_client() is not client
    await close_client()


@pytest.mark.anyio
async def test_close_client_without_singleton_is_noop() -> None:
    await close_client()
    await close_client()


@pytest.mark.anyio
async def test_get_returns_json(httpx2_mock: respx.Router, kc: KeitaroClient) -> None:
    httpx2_mock.get(f"{BASE}/domains").respond(200, json=[{"id": 1}])
    assert (await kc.domains()) == [{"id": 1}]  # type: ignore[comparison-overlap]


@pytest.mark.anyio
async def test_traffic_sources(httpx2_mock: respx.Router, kc: KeitaroClient) -> None:
    httpx2_mock.get(f"{BASE}/traffic_sources").respond(200, json=[{"id": 3}])
    assert (await kc.traffic_sources()) == [{"id": 3}]  # type: ignore[comparison-overlap]


@pytest.mark.anyio
async def test_empty_response_returns_none(
    httpx2_mock: respx.Router, kc: KeitaroClient
) -> None:
    httpx2_mock.delete(f"{BASE}/campaigns/1").respond(204)
    assert await kc._request("DELETE", "/campaigns/1") is None


@pytest.mark.anyio
async def test_http_error_is_passed_through(
    httpx2_mock: respx.Router, kc: KeitaroClient
) -> None:
    httpx2_mock.get(f"{BASE}/offers").respond(404, text="not found")
    with pytest.raises(HTTPException) as exc:
        await kc.offers()
    assert exc.value.status_code == 404
    assert "not found" in exc.value.detail


@pytest.mark.anyio
async def test_transport_error_becomes_502(
    httpx2_mock: respx.Router,
    kc: KeitaroClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    httpx2_mock.get(f"{BASE}/groups").mock(side_effect=httpx2.ConnectError("boom"))
    with (
        caplog.at_level(logging.WARNING, logger="app.keitaro"),
        pytest.raises(HTTPException) as exc,
    ):
        await kc.groups()
    assert exc.value.status_code == 502
    assert "Keitaro unreachable" in caplog.text
    assert "GET /groups" in caplog.text


@pytest.mark.anyio
async def test_http_error_is_logged(
    httpx2_mock: respx.Router,
    kc: KeitaroClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    httpx2_mock.get(f"{BASE}/offers").respond(404, text="not found")
    with (
        caplog.at_level(logging.WARNING, logger="app.keitaro"),
        pytest.raises(HTTPException),
    ):
        await kc.offers()
    assert "Keitaro rejected" in caplog.text
    assert "404" in caplog.text


@pytest.mark.anyio
async def test_groups_sends_type_param(
    httpx2_mock: respx.Router, kc: KeitaroClient
) -> None:
    route = httpx2_mock.get(f"{BASE}/groups").respond(200, json=[])
    assert (await kc.groups()) == []
    assert route.calls.last.request.url.params["type"] == "campaigns"


@pytest.mark.anyio
async def test_create_campaign_sends_json(
    httpx2_mock: respx.Router, kc: KeitaroClient
) -> None:
    route = httpx2_mock.post(f"{BASE}/campaigns").respond(200, json={"id": 5})
    assert (await kc.create_campaign({"name": "x"})) == {"id": 5}
    assert json.loads(route.calls.last.request.content) == {"name": "x"}


@pytest.mark.anyio
async def test_campaign_reads(httpx2_mock: respx.Router, kc: KeitaroClient) -> None:
    httpx2_mock.get(f"{BASE}/campaigns/9").respond(200, json={"id": 9})
    httpx2_mock.get(f"{BASE}/campaigns/9/streams").respond(200, json=[])
    assert (await kc.get_campaign(9))["id"] == 9
    assert (await kc.campaign_streams(9)) == []


@pytest.mark.anyio
async def test_stream_writes(httpx2_mock: respx.Router, kc: KeitaroClient) -> None:
    httpx2_mock.post(f"{BASE}/streams").respond(200, json={"id": 1})
    httpx2_mock.put(f"{BASE}/streams/1").respond(200, json={"id": 1})
    assert (await kc.create_stream({"a": 1})) == {"id": 1}
    assert (await kc.update_stream(1, {"b": 2})) == {"id": 1}


@pytest.mark.anyio
async def test_delete_campaign(httpx2_mock: respx.Router, kc: KeitaroClient) -> None:
    httpx2_mock.delete(f"{BASE}/campaigns/4").respond(200, json={"id": 4})
    assert (await kc.delete_campaign(4)) == {"id": 4}


@pytest.mark.anyio
async def test_report_builds_body(httpx2_mock: respx.Router, kc: KeitaroClient) -> None:
    route = httpx2_mock.post(f"{BASE}/report/build").respond(200, json={"rows": []})
    assert (await kc.report(7, ["offer_id"], interval="all_time")) == {"rows": []}
    body = json.loads(route.calls.last.request.content)
    assert body["range"] == {"interval": "all_time"}
    assert body["dimensions"] == ["offer_id"]
    assert body["filters"] == [
        {"name": "campaign_id", "operator": "EQUALS", "expression": 7}
    ]


@pytest.mark.anyio
async def test_retries_on_transient_status_then_succeeds(
    httpx2_mock: respx.Router, kc: KeitaroClient
) -> None:
    sleeps: list[float] = []
    kc._sleep = lambda d: sleeps.append(float(d))
    kc.MAX_ATTEMPTS = 3
    responses = [
        respx.MockResponse(503, text="busy"),
        respx.MockResponse(200, json=[{"id": 1, "name": "g"}]),
    ]
    httpx2_mock.get(f"{BASE}/groups").mock(side_effect=responses)
    assert (await kc.groups()) == [{"id": 1, "name": "g"}]
    assert len(sleeps) == 1


@pytest.mark.anyio
async def test_retries_on_connect_error_then_succeeds(
    httpx2_mock: respx.Router, kc: KeitaroClient
) -> None:
    sleeps: list[float] = []
    kc._sleep = lambda d: sleeps.append(float(d))
    kc.MAX_ATTEMPTS = 3
    httpx2_mock.get(f"{BASE}/groups").mock(
        side_effect=[
            httpx2.ConnectError("boom"),
            respx.MockResponse(200, json=[]),
        ]
    )
    assert (await kc.groups()) == []
    assert len(sleeps) == 1


@pytest.mark.anyio
async def test_retries_respect_retry_after(
    httpx2_mock: respx.Router, kc: KeitaroClient
) -> None:
    sleeps: list[float] = []
    kc._sleep = lambda d: sleeps.append(float(d))
    kc.MAX_ATTEMPTS = 2
    httpx2_mock.get(f"{BASE}/groups").mock(
        side_effect=[
            respx.MockResponse(429, text="slow", headers={"Retry-After": "0.5"}),
            respx.MockResponse(200, json=[]),
        ]
    )
    assert (await kc.groups()) == []
    assert sleeps == [0.5]


@pytest.mark.anyio
async def test_raises_after_max_attempts(
    httpx2_mock: respx.Router, kc: KeitaroClient
) -> None:
    sleeps: list[float] = []
    kc._sleep = lambda d: sleeps.append(float(d))
    kc.MAX_ATTEMPTS = 2
    httpx2_mock.get(f"{BASE}/groups").mock(
        return_value=respx.MockResponse(503, text="busy")
    )
    with pytest.raises(HTTPException) as exc:
        await kc.groups()
    assert exc.value.status_code == 503
    assert len(sleeps) == 1


@pytest.mark.anyio
async def test_retries_handle_invalid_retry_after(
    httpx2_mock: respx.Router, kc: KeitaroClient
) -> None:
    sleeps: list[float] = []
    kc._sleep = lambda d: sleeps.append(float(d))
    kc.MAX_ATTEMPTS = 2
    httpx2_mock.get(f"{BASE}/groups").mock(
        side_effect=[
            respx.MockResponse(
                429, text="slow", headers={"Retry-After": "not-a-number"}
            ),
            respx.MockResponse(200, json=[]),
        ]
    )
    assert (await kc.groups()) == []
    assert sleeps == [0.0]


@pytest.mark.anyio
async def test_report_with_date_range(
    httpx2_mock: respx.Router, kc: KeitaroClient
) -> None:
    httpx2_mock.post(f"{BASE}/report/build").respond(200, json={"rows": [], "total": 0})
    rep = await kc.report(7, ["offer_id"], date_from="2026-01-01", date_to="2026-02-01")
    assert rep == {"rows": [], "total": 0}
