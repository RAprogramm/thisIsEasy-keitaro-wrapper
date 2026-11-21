"""Request-scoped logging: request ids, formatters, and the access log."""

import contextvars
import json as _json
import logging
import sys
import time
import uuid
from typing import Any

from starlette.requests import Request

from .config import settings

logger = logging.getLogger(__name__)
_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)
_PROBE_PATHS = frozenset({"/health", "/healthz", "/readyz"})


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


def configure_logging() -> None:
    """Configure root logging once, without clobbering an existing setup."""
    if logging.root.handlers:
        logging.root.setLevel(settings.log_level)
        return
    if settings.log_format.lower() == "json":  # pragma: no cover
        formatter: logging.Formatter = _JsonFormatter()  # pragma: no cover
    else:  # pragma: no cover
        formatter = logging.Formatter(  # pragma: no cover
            "%(asctime)s %(levelname)s %(name)s [%(request_id)s]: %(message)s"
        )  # pragma: no cover
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_RequestIdFilter())
    handler.setFormatter(formatter)
    logging.root.addHandler(handler)
    logging.root.setLevel(settings.log_level)


async def request_id_middleware(request: Request, call_next: Any) -> Any:
    """Assign/propagate a request id and store it in a context var.

    Registered last so it is the outermost middleware: every log line this
    process emits for the request, including the access log, carries the id.
    """
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    token = _request_id_var.set(rid)
    response = None
    try:
        response = await call_next(request)
    finally:
        _request_id_var.reset(token)
        if response is not None:
            response.headers["X-Request-ID"] = rid
    if response is None:  # pragma: no cover
        raise RuntimeError("request pipeline returned no response")
    return response


async def log_requests(request: Request, call_next: Any) -> Any:
    """Log every request with method, path, status and duration.

    Liveness and readiness probes are logged at DEBUG so that periodic
    monitoring traffic does not drown the INFO stream.
    """
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:  # pragma: no cover
        logger.exception("request failed: %s %s", request.method, request.url.path)
        raise
    duration_ms = (time.perf_counter() - start) * 1000
    level = logging.DEBUG if request.url.path in _PROBE_PATHS else logging.INFO
    logger.log(
        level,
        "%s %s -> %d (%.1f ms)",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response
