"""C-22: Valuator interface and the flip-comparables valuator (A-26 ``valuation.schema.json``).

An estimate with evidence, never an appraisal: ``not_an_appraisal`` is always true, a range
exists only when comps support it, and a subject we cannot value (home, vehicle) returns
UNKNOWN with a reason, never a number. Pure and deterministic: same item + bundle, same output.
Bundle shape is the estimator's (``comps`` / ``as_is_comps`` of kind sold|asking).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import ROUND_HALF_UP, Decimal

from .comps import _pct
from .config import ScoringConfig, load_config
from .numeric import D

VALUATION_VERSION = "1.0.0"
_RANGES = ("suggested_list", "likely_sale", "fast_sale", "as_is", "after_repair")
_FLIP_KINDS = {"trailer": "trailer", "mower": "mower", "other_asset": "other",
               **{c: "equipment" for c in ("generator", "welder", "compressor", "tool", "commercial_equipment", "mechanical_equipment")}}
_Q25, _Q50, _Q75 = Decimal("0.25"), Decimal("0.5"), Decimal("0.75")


def _whole(x: Decimal) -> int:
    return int(x.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _rng(lo: Decimal, hi: Decimal) -> dict:
    return {"low": _whole(lo), "high": _whole(hi)}


def _unknown(kind: str, item: dict, reason: str, unknowns: list[str]) -> dict:
    return {"valuation_version": VALUATION_VERSION,
            "subject": {"kind": kind, **({"item_id": item["item_id"]} if item.get("item_id") else {})},
            "ranges": {k: None for k in _RANGES}, "confidence": "UNKNOWN", "evidence": [],
            "not_an_appraisal": True, "unknowns": unknowns, "reason_unknown": reason}


class Valuator(ABC):
    """value(item, bundle, as_of) -> valuation.schema.json document."""

    @abstractmethod
    def supports(self, item: dict) -> bool: ...

    @abstractmethod
    def value(self, item: dict, bundle: dict | None, as_of: str) -> dict: ...


class _StubValuator(Valuator):
    kind = ""
    categories: tuple[str, ...] = ()

    def supports(self, item: dict) -> bool:
        return item.get("category") in self.categories

    def value(self, item: dict, bundle: dict | None, as_of: str) -> dict:
        return _unknown(self.kind, item, f"No {self.kind} valuator is built; returning UNKNOWN rather than a number.",
                        ["property or vehicle record", "comps", "condition inspection"])


class HomeValuator(_StubValuator):
    kind = "home"
    categories = ("home",)


class VehicleValuator(_StubValuator):
    kind = "vehicle"
    categories = ("vehicle", "project_vehicle")


class FlipComparablesValuator(Valuator):
    def __init__(self, cfg: ScoringConfig | None = None):
        self.cfg = cfg or load_config()

    def supports(self, item: dict) -> bool:
        return item.get("type") == "flip" and item.get("category") in _FLIP_KINDS

    def value(self, item: dict, bundle: dict | None, as_of: str) -> dict:
        bundle = bundle or {}
        kind = _FLIP_KINDS.get(item.get("category"), "other") if item.get("type") == "flip" else "other"
        if not self.supports(item):
            return _unknown(kind, item, f"FlipComparablesValuator does not value {item.get('type')}/{item.get('category')}.",
                            ["supported flip category"])
        comps = bundle.get("comps") or []
        sold = [c for c in comps if c.get("kind") == "sold"]
        asking = [c for c in comps if c.get("kind") == "asking"]
        evidence = [self._ev(c, "sold_comp") for c in sold] + [self._ev(c, "asking_comp") for c in asking]
        ranges: dict = {k: None for k in _RANGES}
        unknowns: list[str] = []
        if sold:
            xs = sorted(D(c["price"]) for c in sold)
            used = xs[int(self.cfg.num("comps.trim_each_side")):-int(self.cfg.num("comps.trim_each_side"))] \
                if len(xs) >= 5 and int(self.cfg.num("comps.trim_each_side")) > 0 else xs
            p25, p50, p75 = (_pct(used, q) for q in (_Q25, _Q50, _Q75))
            ranges["likely_sale"] = _rng(p25, p75)
            ranges["suggested_list"] = _rng(p50, used[-1])
            ranges["fast_sale"] = _rng(used[0], p25)
            confidence = "high" if len(sold) >= 5 else "medium" if len(sold) >= 3 else "low"
        elif asking:
            xs = sorted(D(c["price"]) for c in asking)
            ranges["suggested_list"] = _rng(xs[0], xs[-1])
            confidence = "low"
            unknowns.append("no sold comps: only the asking range is shown")
        else:
            return _unknown(kind, item, "No comps supplied; a value is never guessed from the title.", ["sold comps"])
        as_is = [D(c["price"]) for c in bundle.get("as_is_comps") or [] if c.get("kind") == "sold"]
        if as_is:
            as_is.sort()
            cand = _rng(_pct(as_is, _Q25), _pct(as_is, _Q75))
            if ranges["likely_sale"] and ranges["suggested_list"] and cand["high"] <= ranges["suggested_list"]["high"] \
                    and cand["low"] <= ranges["likely_sale"]["high"]:
                ranges["as_is"] = cand
                evidence += [self._ev(c, "sold_comp", "as-is condition") for c in bundle["as_is_comps"] if c.get("kind") == "sold"]
            else:
                unknowns.append("as is: as-is comps are not below the working-condition range; not used")
        ev = bundle.get("evidence") or {}
        repair_known = ev.get("fault_identified") or (bundle.get("overrides") or {}).get("rehab.repair_scope_known", {}).get("value")
        if repair_known and ranges["likely_sale"] and (not ranges["as_is"] or ranges["as_is"]["high"] <= ranges["likely_sale"]["high"]):
            ranges["after_repair"] = dict(ranges["likely_sale"])
        why = {"after_repair": "needs a diagnosed fault and repair scope", "as_is": "needs sold as-is comps"}
        for k in _RANGES:
            if ranges[k] is None and not any(k.replace("_", " ") in u for u in unknowns):
                unknowns.append(f"{k.replace('_', ' ')} {why.get(k, 'needs sold comps')}")
        return {"valuation_version": VALUATION_VERSION,
                "subject": {"kind": kind, **({"item_id": item["item_id"]} if item.get("item_id") else {})},
                "ranges": ranges, "confidence": confidence, "evidence": evidence,
                "not_an_appraisal": True, "unknowns": unknowns}

    @staticmethod
    def _ev(c: dict, kind: str, note: str = "") -> dict:
        e = {"kind": kind, "ref": c.get("url") or c["provenance_id"], "provenance_id": c["provenance_id"]}
        n = "; ".join(x for x in (note, f"price {c['price']}", f"sold {c['sold_date']}" if c.get("sold_date") else "") if x)
        return {**e, "note": n}


def valuator_for(item: dict, cfg: ScoringConfig | None = None) -> Valuator:
    for v in (HomeValuator(), VehicleValuator()):
        if v.supports(item):
            return v
    return FlipComparablesValuator(cfg)
