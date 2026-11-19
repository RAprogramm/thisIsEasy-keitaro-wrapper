"""Application factory: routes, static UI, lifespan, and health endpoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .keitaro import close_client
from .routers import creator, editor


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Close the shared HTTP client so connections are released on shutdown."""
    yield
    close_client()


app = FastAPI(title="Keitaro wrapper", lifespan=lifespan)
app.include_router(creator.router)
app.include_router(editor.router)

STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/healthz", tags=["ops"])
def healthz() -> JSONResponse:
    """Liveness probe: the process is up and serving requests."""
    return JSONResponse({"status": "ok"})
