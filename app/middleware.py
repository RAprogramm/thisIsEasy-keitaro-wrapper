"""HTTP middlewares: per-IP rate limiting and security header defaults."""

import threading
import time
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .config import settings

_rate_limit_state: dict[str, list[float]] = {}
_rate_limit_lock = threading.Lock()


async def rate_limit(request: Request, call_next: Any) -> Any:
    """Simple per-IP sliding-window limiter for mutating endpoints.

    Counters are per-process by design; see README "Scaling & state".
    """
    if request.method in (
        "POST",
        "DELETE",
        "PUT",
        "PATCH",
    ) and request.url.path.startswith("/api"):
        client_ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        window = 60.0
        limit = settings.rate_limit_per_minute
        with _rate_limit_lock:
            # Evict stale buckets once the table grows, so a flood of distinct
            # client IPs cannot grow memory without bound.
            if len(_rate_limit_state) > 1000:
                cutoff = now - window
                for ip in [
                    ip
                    for ip, ts in _rate_limit_state.items()
                    if not ts or ts[-1] < cutoff
                ]:
                    del _rate_limit_state[ip]
            bucket = [
                t for t in _rate_limit_state.get(client_ip, []) if now - t < window
            ]
            if len(bucket) >= limit:
                _rate_limit_state[client_ip] = bucket
                return JSONResponse(
                    status_code=429, content={"detail": "Rate limit exceeded"}
                )
            bucket.append(now)
            _rate_limit_state[client_ip] = bucket
    return await call_next(request)


async def security_headers(request: Request, call_next: Any) -> Any:
    """Add a minimal set of security headers to every response."""
    response: Response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response
