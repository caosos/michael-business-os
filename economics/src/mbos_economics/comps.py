"""Sold-comps aggregation (research §14, AT-3).

Rule: SOLD prices only; when n >= 5 drop ``trim_each_side`` lowest and highest;
expected = median, low/high = 25th/75th percentile (linear interpolation on the
sorted, trimmed list). n == 0 gives no estimate (UNKNOWN), never a guess.
"""

from __future__ import annotations

from decimal import Decimal

from .config import ScoringConfig
from .numeric import D, money


def _pct(xs: list[Decimal], q: Decimal) -> Decimal:
    pos = (len(xs) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def aggregate_sold_comps(comps: list[dict], cfg: ScoringConfig) -> dict | None:
    prices = sorted(D(c["sold_price"]) for c in comps if c.get("sold_price") is not None)
    if not prices:
        return None
    trim = int(cfg.num("comps.trim_each_side"))
    if len(prices) >= 5 and trim > 0:
        prices = prices[trim:-trim]
    return {
        "n_used": len(prices),
        "comp_price_low": money(_pct(prices, Decimal("0.25"))),
        "comp_price_expected": money(_pct(prices, Decimal("0.5"))),
        "comp_price_high": money(_pct(prices, Decimal("0.75"))),
    }
