"""Application factory: routes, static UI, lifespan, logging and health endpoint."""

import contextvars
import json as _json
import logging
import sys
import threading
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from starlette.middleware.gzip import GZipMiddleware

from .config import settings
from .db import engine
from .keitaro import close_client
from .routers import creator, editor

logger = logging.getLogger(__name__)
_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)
_rate_limit_state: dict[str, list[float]] = {}
_rate_limit_lock = threading.Lock()


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = _request_id_var.get()
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", _request_id_var.get()),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return _json.dumps(payload, ensure_ascii=False)


def _configure_logging() -> None:
    """Configure root logging once, without clobbering an existing setup."""
    if logging.root.handlers:
        logging.root.setLevel(settings.log_level)
        return
    if settings.log_format.lower() == "json":
        formatter: logging.Formatter = _JsonFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s [%(request_id)s]: %(message)s"
        )
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_RequestIdFilter())
    handler.setFormatter(formatter)
    logging.root.addHandler(handler)
    logging.root.setLevel(settings.log_level)


_configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Close the shared HTTP client so connections are released on shutdown."""
    logger.info("application startup")
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("database reachable")
    except Exception as e:  # pragma: no cover
        logger.error("database unreachable at startup: %s", e)
    yield
    close_client()
    engine.dispose()
    logger.info("application shutdown")


app = FastAPI(title="Keitaro wrapper", lifespan=lifespan)
app.include_router(creator.router)
app.include_router(editor.router)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            o.strip() for o in settings.cors_origins.split(",") if o.strip()
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")

app.add_middleware(GZipMiddleware, minimum_size=500)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next: Any) -> Any:
    """Assign/propagate a request id and store it in a context var."""
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    token = _request_id_var.set(rid)
    try:
        response = await call_next(request)
    finally:
        _request_id_var.reset(token)
    response.headers["X-Request-ID"] = rid
    return response


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


@app.middleware("http")
async def security_headers(request: Request, call_next: Any) -> Any:
    """Add a minimal set of security headers to every response."""
    from starlette.responses import Response

    response: Response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


@app.middleware("http")
async def rate_limit(request: Request, call_next: Any) -> Any:
    """Simple per-IP sliding-window limiter for mutating endpoints."""
    from starlette.responses import JSONResponse as _JR

    if request.method in (
        "POST",
        "DELETE",
        "PUT",
        "PATCH",
    ) and request.url.path.startswith("/api"):
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        window = 60.0
        limit = settings.rate_limit_per_minute
        with _rate_limit_lock:
            bucket = _rate_limit_state.setdefault(client_ip, [])
            bucket[:] = [t for t in bucket if now - t < window]
            if len(bucket) >= limit:
                return _JR(status_code=429, content={"detail": "Rate limit exceeded"})
            bucket.append(now)
    return await call_next(request)


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
def readyz() -> JSONResponse:
    """Readiness probe: database is reachable."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:  # pragma: no cover
        logger.warning("readiness check failed: %s", e)
        return JSONResponse(status_code=503, content={"status": "not ready"})
    return JSONResponse({"status": "ready"})
