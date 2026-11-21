"""In-process TTL cache for upstream dictionary lookups."""

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any, cast

logger = logging.getLogger(__name__)


class TtlCache[T]:
    """Hold a single value until its TTL elapses, then recompute it.

    The clock is injectable so tests can drive expiry deterministically.

    Args:
        ttl: Lifetime of a cached value, in seconds.
        clock: Monotonic time source; defaults to ``time.monotonic``.

    Returns:
        The cached or freshly computed value from ``get_or_set``.

    Usage example::

        cache = TtlCache[float](ttl=60.0)
        value = cache.get_or_set(lambda: expensive_call())
    """

    def __init__(self, ttl: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl = ttl
        self._clock = clock
        self._expires_at: float | None = None
        self._value: T | None = None

    def _fresh_value(self, now: float) -> T | None:
        """Return the cached value while present and within its TTL, else None."""
        if self._expires_at is not None and now < self._expires_at:
            return self._value
        return None

    def _store(self, value: T, now: float) -> None:
        """Cache ``value`` together with the moment it was computed."""
        self._value = value
        self._expires_at = now + self._ttl

    def _stale_fallback(self) -> T | None:
        """Return the stale value when a failed factory leaves one behind."""
        if self._value is not None:
            logger.warning("cache factory failed; returning stale value")
        return self._value

    def get_or_set(self, factory: Callable[[], T]) -> T:
        """Return the cached value or compute and store a fresh one."""
        now = self._clock()
        fresh = self._fresh_value(now)
        if fresh is not None:
            return fresh
        try:
            value = factory()
        except Exception:
            stale = self._stale_fallback()
            if stale is not None:
                return stale
            raise
        self._store(value, now)
        return value

    async def aget_or_set(self, factory: Callable[[], Any]) -> T:
        """Async variant of ``get_or_set`` for coroutine factories."""
        now = self._clock()
        fresh = self._fresh_value(now)
        if fresh is not None:
            return fresh
        try:
            result = factory()
            if asyncio.iscoroutine(result):
                result = await result
            value = cast(T, result)
        except Exception:
            stale = self._stale_fallback()
            if stale is not None:
                return stale
            raise
        self._store(value, now)
        return value

    def clear(self) -> None:
        """Drop the cached value so the next call recomputes it."""
        self._value = None
        self._expires_at = None
