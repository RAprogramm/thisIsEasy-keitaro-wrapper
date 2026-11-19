"""Performance benchmarks for hot paths."""

from app.models import StreamOffer
from app.routers.editor import _rebalance


def test_rebalance_benchmark(benchmark: object) -> None:
    def run() -> None:
        offers = [
            StreamOffer(
                keitaro_campaign_id=1,
                stream_id=1,
                offer_id=i,
                status="active",
                pinned=(i == 0),
                share=10 if i == 0 else 0,
            )
            for i in range(20)
        ]
        _rebalance(offers)

    benchmark(run)  # type: ignore[operator]
