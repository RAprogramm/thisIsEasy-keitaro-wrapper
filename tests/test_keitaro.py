"""Tests for the Keitaro HTTP client, with all traffic mocked by respx."""

import json

import httpx
import pytest
import respx
from fastapi import HTTPException

from app.keitaro import KeitaroClient, get_client

BASE = "https://k.test/admin_api/v1"


@pytest.fixture
def kc() -> KeitaroClient:
    return KeitaroClient(base_url="https://k.test", api_key="k")


def test_default_client_uses_settings() -> None:
    client = get_client()
    assert client.base.endswith("/admin_api/v1")
    assert client.headers["Api-Key"]


@respx.mock
def test_get_returns_json(kc: KeitaroClient) -> None:
    respx.get(f"{BASE}/domains").mock(
        return_value=httpx.Response(200, json=[{"id": 1}])
    )
    assert kc.domains() == [{"id": 1}]


@respx.mock
def test_traffic_sources(kc: KeitaroClient) -> None:
    respx.get(f"{BASE}/traffic_sources").mock(
        return_value=httpx.Response(200, json=[{"id": 3}])
    )
    assert kc.traffic_sources() == [{"id": 3}]


@respx.mock
def test_empty_response_returns_none(kc: KeitaroClient) -> None:
    respx.delete(f"{BASE}/campaigns/1").mock(return_value=httpx.Response(204))
    assert kc._request("DELETE", "/campaigns/1") is None


@respx.mock
def test_http_error_is_passed_through(kc: KeitaroClient) -> None:
    respx.get(f"{BASE}/offers").mock(return_value=httpx.Response(404, text="not found"))
    with pytest.raises(HTTPException) as exc:
        kc.offers()
    assert exc.value.status_code == 404
    assert "not found" in exc.value.detail


@respx.mock
def test_transport_error_becomes_502(kc: KeitaroClient) -> None:
    respx.get(f"{BASE}/groups").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(HTTPException) as exc:
        kc.groups()
    assert exc.value.status_code == 502


@respx.mock
def test_groups_sends_type_param(kc: KeitaroClient) -> None:
    route = respx.get(f"{BASE}/groups").mock(return_value=httpx.Response(200, json=[]))
    assert kc.groups() == []
    assert route.calls.last.request.url.params["type"] == "campaigns"


@respx.mock
def test_create_campaign_sends_json(kc: KeitaroClient) -> None:
    route = respx.post(f"{BASE}/campaigns").mock(
        return_value=httpx.Response(200, json={"id": 5})
    )
    assert kc.create_campaign({"name": "x"}) == {"id": 5}
    assert json.loads(route.calls.last.request.content) == {"name": "x"}


@respx.mock
def test_campaign_reads(kc: KeitaroClient) -> None:
    respx.get(f"{BASE}/campaigns/9").mock(
        return_value=httpx.Response(200, json={"id": 9})
    )
    respx.get(f"{BASE}/campaigns/9/streams").mock(
        return_value=httpx.Response(200, json=[])
    )
    assert kc.get_campaign(9)["id"] == 9
    assert kc.campaign_streams(9) == []


@respx.mock
def test_stream_writes(kc: KeitaroClient) -> None:
    respx.post(f"{BASE}/streams").mock(return_value=httpx.Response(200, json={"id": 1}))
    respx.put(f"{BASE}/streams/1").mock(
        return_value=httpx.Response(200, json={"id": 1})
    )
    assert kc.create_stream({"a": 1}) == {"id": 1}
    assert kc.update_stream(1, {"b": 2}) == {"id": 1}


@respx.mock
def test_report_builds_body(kc: KeitaroClient) -> None:
    route = respx.post(f"{BASE}/report/build").mock(
        return_value=httpx.Response(200, json={"rows": []})
    )
    assert kc.report(7, ["offer_id"], interval="all_time") == {"rows": []}
    body = json.loads(route.calls.last.request.content)
    assert body["range"] == {"interval": "all_time"}
    assert body["dimensions"] == ["offer_id"]
    assert body["filters"] == [
        {"name": "campaign_id", "operator": "EQUALS", "expression": 7}
    ]
