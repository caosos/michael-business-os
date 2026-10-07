"""Transport classification and its economic penalty (C-15; ADR-0011 R19).

Transport is an ECONOMIC variable, never a gate. ``transport_input`` returns the explicit
``economics.logistics.transport`` input the engine adds to cash and hours; it is None when the
category/type cannot be classified DEFINITELY (then nothing is assumed and the card shows UNKNOWN).

Michael's capabilities are data (agent-01 ``config/operator_profile.v1.json``): trailer_owned=false,
borrowed_trailer_possible=true, truck_bed_fits "unspecified". A borrowed trailer must be confirmed with a
person; nothing here ever assumes the confirmation.
"""

from __future__ import annotations

from decimal import Decimal

from .config import ScoringConfig
from .numeric import D, fine, money
from .vocab import query_key

_ACQUISITION_EXCLUDED = {"buyer_meet", "deliver", "delivery", "sale_meet"}


def classify_transport(category: str, title: str | None, priors: ScoringConfig) -> tuple[str | None, str | None]:
    """(mode, evidence). ``mode`` is None when not definite. Evidence names the matched vocabulary token."""
    table = priors.get("transport.classification").get(category)
    if not table:
        return None, None
    key = query_key(category, title, priors)
    for token in key.values():
        if token in table and not token.startswith("_"):
            return table[token], token
    if "default" in table:
        return table["default"], "category default"
    return None, None


def trailer_status(profile: dict | None, priors: ScoringConfig) -> str:
    """'owned' or 'borrowed' (a borrowed trailer needs confirmation with the lender)."""
    if profile is not None:
        t = profile.get("transport", {})
        if t.get("trailer_owned"):
            return "owned"
        if t.get("borrowed_trailer_possible"):
            return "borrowed"
        return "borrowed"   # neither owned nor confirmed possible: still priced as borrowed; the card shows it UNKNOWN
    return priors.get("transport.default_trailer_status")


def acquisition_round_trip_miles(trips: list[dict]) -> Decimal:
    return sum((D(t["round_trip_miles"]) for t in trips if t["purpose"] not in _ACQUISITION_EXCLUDED), D(0))


def transport_input(category: str, title: str | None, trips: list[dict], priors: ScoringConfig,
                    profile: dict | None) -> dict | None:
    mode, evidence = classify_transport(category, title, priors)
    if mode is None:
        return None
    out = {"mode": mode, "extra_cash": 0, "extra_hours": 0}
    if mode == "requires_trailer":
        status = trailer_status(profile, priors)
        p = priors.group(f"transport.penalty.requires_trailer_{status}")
        miles = acquisition_round_trip_miles(trips)
        out["extra_cash"] = _num(money(p["flat_cash"] + p["per_mile_cash"] * miles))
        out["extra_hours"] = _num(fine(p["extra_hours"]))
    return out


def difficulty(mode: str | None, one_way_miles: Decimal | None, priors: ScoringConfig) -> tuple[str, str] | None:
    """(easy|moderate|hard, plain-English rule). None when mode or distance is unknown."""
    if mode is None or one_way_miles is None:
        return None
    hard = priors.num("transport.difficulty.hard_one_way_miles_with_trailer")
    mod = priors.num("transport.difficulty.moderate_one_way_miles_without_trailer")
    if mode == "requires_trailer":
        if one_way_miles > hard:
            return "hard", f"needs a trailer and is {one_way_miles:g} mi one way (over {hard:g})"
        return "moderate", "needs a trailer, within normal range"
    if one_way_miles > mod:
        return "moderate", f"fits the truck but is {one_way_miles:g} mi one way (over {mod:g})"
    return "easy", "fits the truck and is close"


def _num(x: Decimal):
    return int(x) if x == x.to_integral_value() else float(str(x))
