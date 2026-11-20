"""Shared search helper behind the autocomplete endpoints."""

from .schemas import DictItem


def search_items(items: list[DictItem], q: str, limit: int) -> list[DictItem]:
    """Filter ``{id, name}`` items by a free-form query.

    An empty (or blank) query returns the first ``limit`` items; a purely
    numeric query prefers an exact ID match and falls back to name matches;
    anything else matches case-insensitive name substrings.

    Args:
        items: candidates to search through.
        q: raw user query.
        limit: maximum number of results.

    Returns:
        At most ``limit`` matching items, in the original order.
    """
    needle = q.strip().casefold()
    if not needle:
        return items[:limit]
    if needle.isascii() and needle.isdigit():
        exact = [i for i in items if str(i.id) == needle]
        if exact:
            return exact
    return [i for i in items if needle in i.name.casefold()][:limit]
