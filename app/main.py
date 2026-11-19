"""Application factory: routes, static UI, lifespan, logging and health endpoint."""

import logging
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .keitaro import close_client
from .routers import creator, editor

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    """Configure root logging once, without clobbering an existing setup."""
    if logging.root.handlers:
        logging.root.setLevel(settings.log_level)
        return
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )


_configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Close the shared HTTP client so connections are released on shutdown."""
    logger.info("application startup")
    yield
    close_client()
    logger.info("application shutdown")


app = FastAPI(title="Keitaro wrapper", lifespan=lifespan)
app.include_router(creator.router)
app.include_router(editor.router)

STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def log_requests(request: Request, call_next: Any) -> Any:
    """Log every request with method, path, status and duration."""
    from starlette.responses import Response

    start = time.perf_counter()
    try:
        response: Response = await call_next(request)
    except Exception:  # pragma: no cover
        logger.exception("request failed: %s %s", request.method, request.url.path)
        raise
    duration_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "%s %s -> %d (%.1f ms)",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Log the traceback and return a generic 500 response."""
    logger.exception(
        "unhandled exception on %s %s", request.method, request.url.path, exc_info=exc
    )
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/healthz", tags=["ops"])
def healthz() -> JSONResponse:
    """Liveness probe: the process is up and serving requests."""
    return JSONResponse({"status": "ok"})
