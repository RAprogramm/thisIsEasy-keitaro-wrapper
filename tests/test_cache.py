"""Tests for the in-process TTL cache."""

from app.cache import TtlCache


def test_cache_returns_cached_value_within_ttl() -> None:
    clock = {"now": 0.0}
    cache: TtlCache[int] = TtlCache(ttl=10.0, clock=lambda: clock["now"])
    calls = {"n": 0}

    def factory() -> int:
        calls["n"] += 1
        return 42

    assert cache.get_or_set(factory) == 42
    clock["now"] = 5.0
    assert cache.get_or_set(factory) == 42
    assert calls["n"] == 1


def test_cache_recomputes_after_ttl() -> None:
    clock = {"now": 0.0}
    cache: TtlCache[int] = TtlCache(ttl=10.0, clock=lambda: clock["now"])
    calls = {"n": 0}

    def factory() -> int:
        calls["n"] += 1
        return calls["n"]

    assert cache.get_or_set(factory) == 1
    clock["now"] = 10.0
    assert cache.get_or_set(factory) == 2
    assert calls["n"] == 2


def test_cache_clear_forces_recompute() -> None:
    cache: TtlCache[int] = TtlCache(ttl=10.0, clock=lambda: 0.0)
    calls = {"n": 0}

    def factory() -> int:
        calls["n"] += 1
        return 7

    assert cache.get_or_set(factory) == 7
    cache.clear()
    assert cache.get_or_set(factory) == 7
    assert calls["n"] == 2
