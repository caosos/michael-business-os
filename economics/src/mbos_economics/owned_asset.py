"""C-30: owned-asset path comparison on INCREMENTAL cash from today.

Historical purchase basis is SUNK: reported, never used in any path's net, ROI or ranking. Five paths are
computed with the same fields. Every input comes from human-attested ``Item.research`` entries
(``owned:<name>``, same trust rules as C-27/C-28); a missing input is named in ``unknowns`` and the dependent
figure stays ``None``. No rehab cost, hour count or resale value is ever invented. A past tow is INFERENCE about
the running gear only, never roadworthiness. Pure and deterministic; ``as_of`` is a parameter.

Research fields (value is a number or ``{"low": n, "high": n}``):
``owned:historical_basis_usd`` (sunk), ``owned:<path>:cash|hours|resale|days`` for path in sell, minimal, themed,
convert, ``owned:keep:value|cash|hours`` (personal-use value), ``owned:tailgate_months`` (list of 1-12),
``owned:past_tow`` (text), ``owned:structure`` / ``tires`` / ``suspension`` / ``hubs_bearings`` / ``lights_wiring``
/ ``burners_work`` (inspection answers; basis FACT still means "stated", never verified).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from .config import ScoringConfig, load_config
from .numeric import D

OWNED_VERSION = "1.0.0"
PATHS = ("SELL_AS_IS_OR_PART_OUT", "MINIMAL_REHAB_FLIP", "THEMED_VALUE_ADD_FLIP", "CONVERT", "KEEP")
_KEY = {"SELL_AS_IS_OR_PART_OUT": "sell", "MINIMAL_REHAB_FLIP": "minimal", "THEMED_VALUE_ADD_FLIP": "themed",
        "CONVERT": "convert", "KEEP": "keep"}
_SAFETY = ("tires", "structure", "suspension", "hubs_bearings", "lights_wiring", "burners_work")
_BASES = ("FACT", "INFER", "REC", "UNK")


def is_owned_asset(item: dict) -> bool:
    return item.get("type") == "owned_asset" or bool(item.get("owned_asset"))


def _entries(item: dict) -> dict:
    out: dict = {}
    for r in item.get("research") or []:
        f = r.get("field", "")
        if (f.startswith("owned:") and r.get("basis") in _BASES and r.get("entered_by")
                and str(r.get("provenance_id", "")).startswith("prov_")):
            out[f[6:]] = r
    return out


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v < 1e7


def _rng(e):
    """(low, high) Decimals from a number or {'low','high'}; None when absent or malformed."""
    if e is None:
        return None
    v = e.get("value")
    if _num(v):
        return D(v), D(v)
    if isinstance(v, dict) and _num(v.get("low")) and _num(v.get("high")) and v["low"] <= v["high"]:
        return D(v["low"]), D(v["high"])
    return None


def _out(r):
    return None if r is None else {"low": float(r[0]), "high": float(r[1])}


def _mid(r):
    return (r[0] + r[1]) / 2


def _season(months, as_of: str, days):
    if not months:
        return {"status": "UNKNOWN", "missing": "owned:tailgate_months"}
    d0 = datetime.fromisoformat(as_of.replace("Z", "+00:00")).date()
    now_in = d0.month in months
    out = {"status": "IN_SEASON" if now_in else "OFF_SEASON", "months": sorted(months)}
    if days is not None:
        ready = d0 + timedelta(days=int(days[1]))
        out["ready_in_season_at_worst_case"] = ready.month in months
    return out


def _roadworthiness(e: dict) -> dict:
    answered = [k for k in _SAFETY if k in e]
    if answered and len(answered) == len(_SAFETY):
        conf, why = "STATED_NOT_VERIFIED", "all safety answers are Michael's statements; nothing is inspected or verified"
    elif answered:
        conf, why = "PARTIAL", "some safety answers stated; the rest are UNKNOWN"
    elif "past_tow" in e:
        conf, why = "INFERENCE", "a past tow shows the running gear moved once; it says nothing about structure, bearings, suspension, lights or title now"
    else:
        conf, why = "UNKNOWN", "no tow history and no inspection answers"
    return {"confidence": conf, "why": why, "past_tow_basis": "INFERENCE" if "past_tow" in e else None,
            "missing_safety_inputs": [f"owned:{k}" for k in _SAFETY if k not in e]}


def _path(name: str, e: dict, rw: dict, season_months, as_of: str, w: Decimal) -> dict:
    k = _KEY[name]
    keep = name == "KEEP"
    cash = _rng(e.get(f"{k}:cash"))
    hours = _rng(e.get(f"{k}:hours"))
    days = _rng(e.get(f"{k}:days"))
    value = _rng(e.get("keep:value" if keep else f"{k}:resale"))
    # Selling as-is needs no outlay: a structural zero, not an invented estimate.
    cash_note = None
    if name == "SELL_AS_IS_OR_PART_OUT" and cash is None:
        cash, cash_note = (Decimal(0), Decimal(0)), "no outlay to sell as-is (structural zero); fees not modelled"
    missing = []
    if cash is None:
        missing.append(f"owned:{k}:cash")
    if hours is None:
        missing.append(f"owned:{k}:hours")
    if value is None:
        missing.append("owned:keep:value" if keep else f"owned:{k}:resale")
    if days is None and not keep:
        missing.append(f"owned:{k}:days")
    if not keep and not season_months:
        missing.append("owned:tailgate_months")
    fields = {"incremental_cash": _out(cash), "operator_hours": _out(hours), "days_to_cash": None if keep else _out(days),
              "finished_resale_range": None if keep else _out(value), "personal_use_value": _out(value) if keep else None}
    net = per_dollar = per_hour = ranked = None
    if cash is not None and value is not None:
        net_r = (value[0] - cash[1], value[1] - cash[0])
        nm = _mid(net_r)
        net = _out(net_r)
        cm = _mid(cash)
        per_dollar = float(nm / cm) if cm > 0 else None
        if hours is not None:
            hm = _mid(hours)
            per_hour = float(nm / hm) if hm > 0 else None
            ranked = float(nm - hm * w)
    structural = e.get("structure")
    return {
        "path": name, **fields, "net_incremental": net, "profit_per_incremental_dollar": per_dollar,
        "profit_per_dollar_note": ("no incremental cash: ratio undefined, not infinite" if cash is not None and _mid(cash) == 0 else cash_note),
        "profit_per_hour": per_hour, "net_after_time_value": ranked,
        "risk": {"structural": (structural or {}).get("value") if structural else "UNKNOWN",
                 "roadworthiness_confidence": rw["confidence"],
                 "applies": name in ("MINIMAL_REHAB_FLIP", "THEMED_VALUE_ADD_FLIP", "CONVERT", "KEEP")},
        "seasonality": None if keep else _season(season_months, as_of, days),
        "computable": ranked is not None, "unknowns": sorted(set(missing)),
        "basis_note": "personal-use value is the owner's own figure, not cash" if keep else None,
    }


def compare_paths(item: dict, as_of: str, cfg: ScoringConfig | None = None) -> dict:
    """Five-path comparison for one owned asset. Sunk basis is reported and excluded from every figure."""
    cfg = cfg or load_config()
    e = _entries(item)
    w = D(cfg.get("time_value.w_min_per_hour"))
    months = (e.get("tailgate_months") or {}).get("value")
    months = [m for m in months if isinstance(m, int) and 1 <= m <= 12] if isinstance(months, list) else []
    rw = _roadworthiness(e)
    paths = [_path(n, e, rw, months, as_of, w) for n in PATHS]
    ok = [p for p in paths if p["computable"]]
    best = max(ok, key=lambda p: (p["net_after_time_value"], -PATHS.index(p["path"]))) if ok else None
    basis = _rng(e.get("historical_basis_usd"))
    unknown_all = sorted({u for p in paths if not p["computable"] for u in p["unknowns"]})
    return {
        "owned_asset_version": OWNED_VERSION, "item_id": item.get("item_id"), "as_of": as_of,
        "decision_basis": "incremental cash from today; historical basis is sunk",
        "sunk_basis": {"historical_basis_usd": _out(basis), "excluded_from": ["net", "roi", "ranking"]},
        "hourly_value_used": float(w), "hourly_value_source": "time_value.w_min_per_hour (coordinator default, not Michael-confirmed)",
        "roadworthiness": rw, "paths": paths,
        "recommendation": ({"path": best["path"], "net_after_time_value": best["net_after_time_value"],
                            "rule": "highest net incremental value minus operator hours at the floor $/h, among fully computable paths",
                            "others_not_computable": [p["path"] for p in paths if not p["computable"]],
                            "caveat": "range midpoints; roadworthiness is " + rw["confidence"]}
                           if best else {"path": "UNKNOWN", "reason": "no path has all inputs", "missing": unknown_all}),
        "unknowns": unknown_all, "dry_run": True,
    }
