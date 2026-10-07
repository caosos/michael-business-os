"""Decimal arithmetic helpers.

All engine arithmetic is done in ``decimal.Decimal`` so results are exact,
platform-independent and reproducible by hand. Every *stored* intermediate is
quantized at the moment it is computed (money 2dp, hours/ratios 4dp, scores 2dp)
and later steps use the quantized value, so a person replaying a scorecard from
its own ``derived`` numbers reaches the same gates and verdict.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Any

ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")

_MONEY = Decimal("0.01")
_FINE = Decimal("0.0001")


def D(x: Any) -> Decimal:
    """Convert an input number to Decimal via its string form (never via binary float)."""
    if isinstance(x, Decimal):
        return x
    if isinstance(x, bool):
        raise TypeError("boolean is not a number")
    if isinstance(x, (int, float, str)):
        return Decimal(str(x))
    raise TypeError(f"not a number: {x!r}")


def money(x: Decimal) -> Decimal:
    """Quantize to cents, half-up."""
    return x.quantize(_MONEY, rounding=ROUND_HALF_UP)


def fine(x: Decimal) -> Decimal:
    """Quantize hours, probabilities and ratios to 4dp, half-up."""
    return x.quantize(_FINE, rounding=ROUND_HALF_UP)


score2 = money  # scores share the 2dp rule


def clamp(x: Decimal, lo: Decimal = ZERO, hi: Decimal = ONE) -> Decimal:
    return max(lo, min(hi, x))


def sqrt(x: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 28
        return x.sqrt()


def to_json_number(x: Decimal) -> int | float:
    """Render a Decimal for JSON output. Values carry <= 4dp so float repr round-trips."""
    if x == x.to_integral_value():
        return int(x)
    return float(str(x))
