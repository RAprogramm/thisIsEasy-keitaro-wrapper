"""Application factory: routes, static UI, lifespan, and error handling."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from starlette.middleware.gzip import GZipMiddleware

from .config import settings
from .db import engine
from .errors import AppError
from .keitaro import close_client
from .middleware import rate_limit, security_headers
from .routers import creator, editor
from .telemetry import configure_logging, log_requests, request_id_middleware

logger = logging.getLogger(__name__)

configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Close the shared HTTP client so connections are released on shutdown.

    Also demotes uvicorn's access log: this service logs every request itself,
    with a request id and duration, so a second copy of each line is noise.
    """
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logger.info("application startup")
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("database reachable")
    except Exception as e:  # pragma: no cover
        logger.error("database unreachable at startup: %s", e)
    yield
    await close_client()
    await engine.dispose()
    logger.info("application shutdown")


app = FastAPI(title="Keitaro wrapper", lifespan=lifespan)
app.include_router(creator.router)
app.include_router(editor.router)

if settings.cors_origins:  # pragma: no cover
    origins = [  # pragma: no cover
        o.strip() for o in settings.cors_origins.split(",") if o.strip()
    ]  # pragma: no cover
    # A wildcard origin is incompatible with credentialed requests in browsers;
    # drop credentials in that case instead of emitting an invalid combination.
    allow_credentials = "*" not in origins  # pragma: no cover
    app.add_middleware(  # pragma: no cover
        CORSMiddleware,  # pragma: no cover
        allow_origins=origins,  # pragma: no cover
        allow_credentials=allow_credentials,  # pragma: no cover
        allow_methods=["*"],  # pragma: no cover
        allow_headers=["*"],  # pragma: no cover
    )  # pragma: no cover

STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")

app.add_middleware(GZipMiddleware, minimum_size=500)

app.middleware("http")(rate_limit)
app.middleware("http")(security_headers)
app.middleware("http")(log_requests)
# Registered last so it is the outermost middleware: every log line and
# response header for a request carries its id.
app.middleware("http")(request_id_middleware)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Map typed application errors onto their HTTP status and detail."""
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(IntegrityError)
async def integrity_error_handler(
    request: Request, exc: IntegrityError
) -> JSONResponse:
    """Map database integrity violations to 409 instead of 500."""
    logger.warning(
        "integrity violation on %s %s: %s", request.method, request.url.path, exc.orig
    )
    return JSONResponse(
        status_code=409, content={"detail": "Conflict: duplicate or invalid reference"}
    )


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


@app.get("/readyz", tags=["ops"])
async def readyz() -> JSONResponse:
    """Readiness probe: database is reachable."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as e:  # pragma: no cover
        logger.warning("readiness check failed: %s", e)
        return JSONResponse(status_code=503, content={"status": "not ready"})
    return JSONResponse({"status": "ready"})
