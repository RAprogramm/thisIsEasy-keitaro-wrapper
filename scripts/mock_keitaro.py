"""Local Keitaro Admin API mock for demo recording.

Implements the endpoints the wrapper uses, with seeded data mirroring the
demo video: a redirect stream (AU -> Google) and a landings stream with
three offers at 33/33/34. Started by ``make demo`` on port 9001.
"""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Keitaro mock")

DB: dict[str, Any] = {
    "domains": [
        {"id": 1, "name": "demo-alpha.example"},
        {"id": 2, "name": "demo-beta.example"},
    ],
    "groups": [{"id": 10, "name": "demo"}, {"id": 11, "name": "test"}],
    "traffic_sources": [
        {"id": 100, "name": "Google Ads"},
        {"id": 101, "name": "Facebook Ads"},
    ],
    "offers": [
        {"id": 18813, "name": "18813 Flexacil [JOINT-PE] [vsl es -] ReactJs v4"},
        {"id": 90001, "name": "90001 Demo Offer Alpha"},
        {"id": 90002, "name": "90002 Demo Offer Beta"},
        {"id": 90003, "name": "90003 Demo Offer Gamma"},
        {"id": 90004, "name": "90004 Demo Offer Delta"},
    ],
    "campaigns": {
        900001: {
            "id": 900001,
            "name": "demo_video_campaign",
            "type": "rotor",
            "state": "active",
            "domain_id": 1,
            "group_id": 10,
            "traffic_source_id": 100,
        }
    },
    "streams": {
        910001: {
            "id": 910001,
            "campaign_id": 900001,
            "name": "AU -> Google",
            "type": "regular",
            "position": 1,
            "weight": 100,
            "state": "active",
            "schema": "redirect",
            "action_type": "http",
            "action_payload": "https://www.google.com/",
            "filters": [{"name": "country", "mode": "accept", "payload": ["AU"]}],
        },
        910002: {
            "id": 910002,
            "campaign_id": 900001,
            "name": "Offer",
            "type": "regular",
            "position": 2,
            "weight": 100,
            "state": "active",
            "schema": "landings",
            "action_type": "http",
            "action_payload": "",
            "filters": [],
            "offers": [
                {"offer_id": 18813, "share": 33, "state": "active"},
                {"offer_id": 90001, "share": 33, "state": "active"},
                {"offer_id": 90002, "share": 34, "state": "active"},
            ],
        },
    },
    "next_campaign_id": 900002,
    "next_stream_id": 910003,
}

STATS = {
    18813: {
        "clicks": 412,
        "campaign_unique_clicks": 300,
        "conversions": 12,
        "revenue": 360.0,
        "cost": 150.0,
        "profit": 210.0,
    },
    90001: {
        "clicks": 198,
        "campaign_unique_clicks": 150,
        "conversions": 5,
        "revenue": 150.0,
        "cost": 80.0,
        "profit": 70.0,
    },
    90002: {
        "clicks": 175,
        "campaign_unique_clicks": 140,
        "conversions": 3,
        "revenue": 90.0,
        "cost": 70.0,
        "profit": 20.0,
    },
    90003: {
        "clicks": 64,
        "campaign_unique_clicks": 50,
        "conversions": 2,
        "revenue": 60.0,
        "cost": 25.0,
        "profit": 35.0,
    },
    90004: {
        "clicks": 21,
        "campaign_unique_clicks": 18,
        "conversions": 0,
        "revenue": 0.0,
        "cost": 10.0,
        "profit": -10.0,
    },
}


def _deny(request: Request) -> JSONResponse | None:
    if not request.headers.get("Api-Key"):
        return JSONResponse({"error": "Access denied by API key"}, status_code=401)
    return None


@app.get("/admin_api/v1/domains")
async def domains(request: Request) -> Any:
    return _deny(request) or DB["domains"]


@app.get("/admin_api/v1/groups")
async def groups(request: Request) -> Any:
    return _deny(request) or DB["groups"]


@app.get("/admin_api/v1/traffic_sources")
async def sources(request: Request) -> Any:
    return _deny(request) or DB["traffic_sources"]


@app.get("/admin_api/v1/offers")
async def offers(request: Request) -> Any:
    return _deny(request) or DB["offers"]


@app.get("/admin_api/v1/offers/{offer_id}")
async def get_offer(request: Request, offer_id: int) -> Any:
    denied = _deny(request)
    if denied:
        return denied
    offer = next((o for o in DB["offers"] if o["id"] == offer_id), None)
    if offer is None:
        return JSONResponse({"error": "Offer not found"}, status_code=404)
    return offer


@app.get("/admin_api/v1/campaigns")
async def campaigns(request: Request) -> Any:
    return _deny(request) or list(DB["campaigns"].values())


@app.get("/admin_api/v1/campaigns/{campaign_id}")
async def get_campaign(request: Request, campaign_id: int) -> Any:
    denied = _deny(request)
    if denied:
        return denied
    campaign = DB["campaigns"].get(campaign_id)
    if campaign is None:
        return JSONResponse({"error": "Campaign not found"}, status_code=404)
    return campaign


@app.post("/admin_api/v1/campaigns")
async def create_campaign(request: Request) -> Any:
    denied = _deny(request)
    if denied:
        return denied
    body = await request.json()
    cid = DB["next_campaign_id"]
    DB["next_campaign_id"] += 1
    campaign = {
        "id": cid,
        "name": body.get("name", f"campaign {cid}"),
        "type": body.get("type", "rotor"),
        "state": "active",
        "domain_id": body.get("domain_id", 1),
        "group_id": body.get("group_id", 10),
        "traffic_source_id": body.get("traffic_source_id", 100),
    }
    DB["campaigns"][cid] = campaign
    return campaign


@app.delete("/admin_api/v1/campaigns/{campaign_id}")
async def delete_campaign(request: Request, campaign_id: int) -> Any:
    denied = _deny(request)
    if denied:
        return denied
    campaign = DB["campaigns"].get(campaign_id)
    if campaign is None:
        return JSONResponse({"error": "Campaign not found"}, status_code=404)
    campaign["state"] = "deleted"
    for stream in DB["streams"].values():
        if stream["campaign_id"] == campaign_id:
            stream["state"] = "deleted"
    return campaign


@app.get("/admin_api/v1/campaigns/{campaign_id}/streams")
async def campaign_streams(request: Request, campaign_id: int) -> Any:
    denied = _deny(request)
    if denied:
        return denied
    if campaign_id not in DB["campaigns"]:
        return JSONResponse({"error": "Campaign not found"}, status_code=404)
    return [s for s in DB["streams"].values() if s["campaign_id"] == campaign_id]


@app.post("/admin_api/v1/streams")
async def create_stream(request: Request) -> Any:
    denied = _deny(request)
    if denied:
        return denied
    body = await request.json()
    sid = DB["next_stream_id"]
    DB["next_stream_id"] += 1
    stream = {
        "id": sid,
        "campaign_id": body["campaign_id"],
        "name": body.get("name", f"stream {sid}"),
        "type": body.get("type", "regular"),
        "position": body.get("position", 1),
        "weight": body.get("weight", 100),
        "state": body.get("state", "active"),
        "schema": body.get("schema", "redirect"),
        "action_type": body.get("action_type", "http"),
        "action_payload": body.get("action_payload", ""),
        "filters": body.get("filters", []),
    }
    if "offers" in body:
        stream["offers"] = body["offers"]
    DB["streams"][sid] = stream
    return stream


@app.put("/admin_api/v1/streams/{stream_id}")
async def update_stream(request: Request, stream_id: int) -> Any:
    denied = _deny(request)
    if denied:
        return denied
    stream = DB["streams"].get(stream_id)
    if stream is None:
        return JSONResponse({"error": "Stream not found"}, status_code=404)
    body = await request.json()
    for key, value in body.items():
        stream[key] = value
    return stream


@app.post("/admin_api/v1/report/build")
async def report(request: Request) -> Any:
    denied = _deny(request)
    if denied:
        return denied
    body = await request.json()
    dims = body.get("dimensions", [])
    if "offer_id" not in dims:
        return {"rows": []}
    campaign_id = next(
        (
            f["expression"]
            for f in body.get("filters", [])
            if f.get("name") == "campaign_id"
        ),
        None,
    )
    stream = next(
        (
            s
            for s in DB["streams"].values()
            if s["campaign_id"] == campaign_id and s.get("schema") == "landings"
        ),
        None,
    )
    rows = []
    for entry in (stream or {}).get("offers", []):
        oid = entry["offer_id"]
        rows.append({"offer_id": oid, **STATS.get(oid, {})})
    return {"rows": rows}


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "mock"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=9001)
