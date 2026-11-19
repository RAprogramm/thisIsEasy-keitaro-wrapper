"""In-process TTL cache for upstream dictionary lookups."""

import logging
import time
from collections.abc import Callable

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

    def get_or_set(self, factory: Callable[[], T]) -> T:
        """Return the cached value or compute and store a fresh one."""
        now = self._clock()
        if (
            self._expires_at is not None
            and now < self._expires_at
            and self._value is not None
        ):
            return self._value
        try:
            value = factory()
        except Exception:
            if self._value is not None:
                logger.warning("cache factory failed; returning stale value")
                return self._value
            raise
        self._value = value
        self._expires_at = now + self._ttl
        return value

    def clear(self) -> None:
        """Drop the cached value so the next call recomputes it."""
        self._value = None
        self._expires_at = None
