"""Weekly Money Mission contract helpers (ADR-0013, `mission.schema.json`).

Pure functions: schema validation plus the invariants JSON Schema cannot express. Nothing here
spends, contacts or publishes. `null` is UNKNOWN and is preserved, never defaulted.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .contracts.schemas import ContractViolation, contracts_dir

_EPS = 0.005  # cents


@lru_cache(maxsize=1)
def _schema() -> dict[str, Any]:
    return json.loads((contracts_dir() / "mission.schema.json").read_text())


def _validator(defn: str) -> Draft202012Validator:
    s = {"$schema": _schema()["$schema"], "$defs": _schema()["$defs"], "$ref": f"#/$defs/{defn}"}
    return Draft202012Validator(s, format_checker=FormatChecker())


def nonfinite_paths(doc: Any, path: str = "") -> list[str]:
    """F-63: NaN / +-Infinity pass JSON-Schema `number`; every contract validator rejects them (also used by campaign/valuation)."""
    import math

    out: list[str] = []
    if isinstance(doc, float) and not math.isfinite(doc):
        out.append(path or "<root>")
    elif isinstance(doc, dict):
        for k, v in doc.items():
            out += nonfinite_paths(v, f"{path}/{k}")
    elif isinstance(doc, list):
        for i, v in enumerate(doc):
            out += nonfinite_paths(v, f"{path}/{i}")
    return out


def _check(defn: str, doc: Any) -> list[str]:
    bad = nonfinite_paths(doc)
    if bad:
        return [f"{b}: non-finite number (NaN/Infinity) is not a valid value" for b in bad]
    return [f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}" for e in _validator(defn).iter_errors(doc)]


def ledger_errors(ledger: dict[str, Any]) -> list[str]:
    errs = _check("capital_ledger", ledger)
    if errs:
        return errs
    imp = ledger.get("principal_impairment", 0)
    if imp > ledger["protected_principal"] + _EPS:
        errs.append("principal_impairment exceeds protected_principal")
    if imp > _EPS and ledger["earned_working_capital"] > _EPS:
        errs.append("principal_impairment while earned_working_capital > 0: losses consume earned capital first")
    expected = ledger["protected_principal"] - imp + ledger["earned_working_capital"] - ledger["capital_deployed"]
    if abs(ledger["available_to_deploy"] - expected) > _EPS:
        errs.append(f"available_to_deploy {ledger['available_to_deploy']} != protected_principal - principal_impairment + earned_working_capital - "
                    f"capital_deployed ({expected})")
    if ledger["capital_deployed"] > ledger["protected_principal"] - imp + max(ledger["earned_working_capital"], 0) + _EPS:
        errs.append("capital_deployed exceeds principal + earned working capital")
    return errs


def plan_errors(plan: dict[str, Any]) -> list[str]:
    errs = _check("mission_plan", plan)
    if errs:
        return errs
    errs += [f"ledger: {e}" for e in ledger_errors(plan["ledger"])]
    legs = plan["legs"]
    spend = sum(l["cash_at_risk"] for l in legs)
    if spend > plan["ledger"]["available_to_deploy"] + _EPS:
        errs.append(f"legs put ${spend:g} at risk but only ${plan['ledger']['available_to_deploy']:g} is available_to_deploy")
    if plan["recommendation"] == "DO_NOT_SPEND" and spend > _EPS:
        errs.append("recommendation DO_NOT_SPEND but legs commit cash")
    if len({l["item_id"] for l in legs}) != len(legs):
        errs.append("an item appears in more than one leg")
    for l in legs:
        r = l["expected_net"]
        vals = [r[k] for k in ("low", "likely", "high")]
        if None not in vals and not (vals[0] <= vals[1] <= vals[2]):
            errs.append(f"{l['item_id']}: expected_net must satisfy low <= likely <= high")
    if plan["recommendation"] == "DEPLOY" and not legs:
        errs.append("recommendation DEPLOY but there are no legs")
    if plan["recommendation"] in ("HOLD", "UNKNOWN") and spend > _EPS:
        errs.append(f"recommendation {plan['recommendation']} but legs commit cash; only DEPLOY may commit cash")
    pw, target = plan["projected_week"], plan["mission"]["weekly_target_usd"]
    for k in ("low", "likely", "high"):  # F-64: a projection can never exceed what its legs can produce
        vals = [l["expected_net"][k] for l in legs]
        if pw[k] is not None and (not legs or None in vals or pw[k] > sum(vals) + _EPS):
            errs.append(f"projected_week.{k} {pw[k]} is not supported by the legs (sum of expected_net.{k} = "
                        f"{'unknown' if None in vals else sum(vals)})")
    if pw["likely"] is None and plan["remaining_gap"] is not None:
        errs.append("projected_week.likely is null (UNKNOWN) so remaining_gap must be null")
    if None not in (pw["low"], pw["likely"], pw["high"]) and not (pw["low"] <= pw["likely"] <= pw["high"]):
        errs.append("projected_week must satisfy low <= likely <= high")
    if target is None and plan["remaining_gap"] is not None:
        errs.append("remaining_gap must be null (UNKNOWN) when weekly_target_usd is null; it is never invented")
    if target is not None and pw["likely"] is not None and plan["remaining_gap"] is not None \
            and abs(plan["remaining_gap"] - (target - pw["likely"])) > _EPS:
        errs.append("remaining_gap != weekly_target_usd - projected_week.likely")
    return errs


def _raise(kind: str, errs: list[str]) -> None:
    if errs:
        raise ContractViolation(kind, errs)


def validate_mission(doc: dict[str, Any]) -> None:
    _raise("mission", _check("mission", doc))


def validate_ledger(doc: dict[str, Any]) -> None:
    _raise("capital_ledger", ledger_errors(doc))


def validate_plan(doc: dict[str, Any]) -> None:
    _raise("mission_plan", plan_errors(doc))
