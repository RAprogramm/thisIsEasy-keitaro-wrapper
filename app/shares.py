"""Pure share arithmetic: validation, rebalancing, and publish payloads.

No database and no network: everything here works on in-memory ``StreamOffer``
rows, so the traffic-split rules can be tested and reused in isolation.
"""

from typing import Any

from .errors import DomainError
from .models import OfferStatus, StreamOffer

ACTIVE_STATUSES = (OfferStatus.ACTIVE, OfferStatus.PENDING_ADD)
REMOVED_STATUSES = (OfferStatus.PENDING_REMOVE, OfferStatus.REMOVED)


def active_offers(offers: list[StreamOffer]) -> list[StreamOffer]:
    """Offers that currently receive traffic, staged additions included."""
    return [o for o in offers if o.status in ACTIVE_STATUSES]


def pinned_share_total(offers: list[StreamOffer]) -> int:
    """Total share locked by pinned offers; the part rebalancing cannot move."""
    return sum(o.share for o in active_offers(offers) if o.pinned)


def active_share_total(offers: list[StreamOffer]) -> int:
    """Total share the stream would publish to Keitaro."""
    return sum(o.share for o in active_offers(offers))


def ensure_pin_allowed(
    offers: list[StreamOffer], target: StreamOffer, pinned: bool
) -> None:
    """Reject pinning that would lock more than the whole stream.

    Args:
        offers: All tracked offers of the stream.
        target: The offer being pinned.
        pinned: New pin state; unpinning is always allowed.

    Raises:
        DomainError: 400 when the pinned shares would exceed 100%.
    """
    if not pinned:
        return
    total = pinned_share_total([o for o in offers if o is not target]) + target.share
    if total > 100:
        raise DomainError(
            f"Сумма закреплённых долей станет {total}% — максимум 100%",
        )


def ensure_removal_keeps_shares(offers: list[StreamOffer], target: StreamOffer) -> None:
    """Reject a removal that leaves only pinned shares that are not 100%.

    Args:
        offers: All tracked offers of the stream.
        target: The offer about to be removed.

    Raises:
        DomainError: 400 when the remaining offers are all pinned and do not
            add up to 100%, because nothing is left to rebalance them.
    """
    remaining = [o for o in active_offers(offers) if o is not target]
    if remaining and all(o.pinned for o in remaining):
        total = sum(o.share for o in remaining)
        if total != 100:
            raise DomainError(
                f"Останутся только закреплённые доли на {total}% — "
                "сначала открепите одну из них",
            )


def ensure_shares_publishable(offers: list[StreamOffer]) -> None:
    """Refuse to publish a stream whose traffic split does not add up.

    Args:
        offers: All tracked offers of the stream about to be pushed.

    Raises:
        DomainError: 400 when no offer is active or the shares are not 100%.
    """
    if not active_offers(offers):
        raise DomainError("В потоке не осталось активных офферов")
    total = active_share_total(offers)
    if total != 100:
        raise DomainError(
            f"Сумма долей активных офферов — {total}%, нужно 100%: "
            "открепите долю или пересчитайте поток",
        )


def rebalance(offers: list[StreamOffer]) -> list[StreamOffer]:
    """Split 100% across non-pinned active offers; removed ones get 0."""
    pinned_sum = pinned_share_total(offers)
    participants = [o for o in offers if not o.pinned and o.status in ACTIVE_STATUSES]
    # Never hand out negative shares: if pinned offers already fill (or
    # overfill) the 100%, unpinned participants simply receive nothing.
    remaining = max(0, 100 - pinned_sum)
    for o in offers:
        if o.status in REMOVED_STATUSES:
            o.share = 0
    if participants:
        base, rest = divmod(remaining, len(participants))
        for i, o in enumerate(participants):
            o.share = base + (rest if i == 0 else 0)
    return offers


def stream_payload(offers: list[StreamOffer]) -> dict[str, Any]:
    """Keitaro PUT updates only the fields sent, so we send just the offer list."""
    return {
        "offers": [
            {
                "offer_id": o.offer_id,
                "share": o.share,
                "state": OfferStatus.ACTIVE,
            }
            for o in offers
            if o.status in ACTIVE_STATUSES
        ]
    }


def settle(offers: list[StreamOffer]) -> None:
    """Undo rebalancing noise once the stream matches its published state.

    Removing and restoring an offer (or pinning and unpinning) leaves shares
    equally split, which can differ from the exact shares Keitaro already
    has. When nothing is staged any more, shares snap back to the published
    values so the stream stops claiming to be dirty; while changes are
    staged, a rebalance keeps the active shares publishable.

    Args:
        offers: All tracked offers of the stream after an undone change.
    """
    if all(
        o.status == OfferStatus.ACTIVE and o.pinned == o.published_pinned
        for o in offers
    ) and active_share_total(offers) == sum(o.published_share for o in offers):
        for o in offers:
            o.share = o.published_share
        return
    if any(o.status != OfferStatus.ACTIVE for o in offers) or (
        active_share_total(offers) != 100
    ):
        rebalance(offers)


def is_dirty(offers: list[StreamOffer]) -> bool:
    """True when local state differs from what was last published to Keitaro."""
    return any(
        o.status in (OfferStatus.PENDING_ADD, OfferStatus.PENDING_REMOVE)
        or o.share != o.published_share
        or o.pinned != o.published_pinned
        for o in offers
    )
