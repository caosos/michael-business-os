"""Valuation contract helpers (ADR-0013, `valuation.schema.json`). An estimate, never an appraisal."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .contracts.schemas import ContractViolation, contracts_dir


@lru_cache(maxsize=1)
def _v() -> Draft202012Validator:
    return Draft202012Validator(json.loads((contracts_dir() / "valuation.schema.json").read_text()), format_checker=FormatChecker())


_APPRAISAL_CLAIM = __import__("re").compile(r"\bappraised\b|\b(licensed|certified|official|formal)\s+appraisal\b|\bappraisal value\b|\bguarantee[sd]?\b|\bappraiser\b|\bcertified\b", __import__("re").I)


def _strings(doc: Any) -> list[str]:
    if isinstance(doc, str):
        return [doc]
    if isinstance(doc, dict):
        return [x for k, v in doc.items() if k != "not_an_appraisal" for x in _strings(v)]
    if isinstance(doc, list):
        return [x for v in doc for x in _strings(v)]
    return []


def errors(doc: Any) -> list[str]:
    from .mission import nonfinite_paths

    bad = nonfinite_paths(doc)
    if bad:
        return [f"{b}: non-finite number is not a valid value" for b in bad]
    errs = [f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}" for e in _v().iter_errors(doc)]
    if errs:
        return errs
    ranges = doc["ranges"]
    known = {k: r for k, r in ranges.items() if r is not None}
    for k, r in known.items():
        if r["low"] > r["high"]:
            errs.append(f"ranges.{k}: low > high")
    if known and not doc["evidence"]:
        errs.append("a range without evidence is a guess: add evidence or return null (UNKNOWN)")
    if not known and doc["confidence"] not in ("UNKNOWN", "low"):
        errs.append("no ranges but confidence is not UNKNOWN/low")
    if not known and not doc.get("reason_unknown"):
        errs.append("all ranges UNKNOWN requires reason_unknown")
    if known and doc["confidence"] == "high" and sum(1 for e in doc["evidence"] if e["kind"] in ("sold_comp", "record")) < 2:
        errs.append("confidence high requires at least two independent sold comps or records, not one comp or asking comps/priors")
    ai, ar = ranges.get("as_is"), ranges.get("after_repair")
    if ai and ar and (ai["high"] > ar["high"] or ai["low"] > ar["low"]):
        errs.append("as_is is above after_repair (repair cannot lower value in this model)")
    if known and doc["confidence"] == "medium" and not any(e["kind"] != "prior" for e in doc["evidence"]):
        errs.append("confidence medium needs at least one non-prior evidence item (priors alone are low)")
    if known:
        unk = " ".join(doc["unknowns"]).lower()
        for k, r in ranges.items():
            pass
        for k in (k for k, r in doc["ranges"].items() if r is None):
            if k.replace("_", " ") not in unk and k not in unk:
                errs.append(f"range {k} is null but not reconciled in unknowns")
    sl, ls, fs = ranges.get("suggested_list"), ranges.get("likely_sale"), ranges.get("fast_sale")
    if fs and sl and fs["high"] > sl["high"]:
        errs.append("fast_sale.high exceeds suggested_list.high")
    if fs and ls and fs["low"] > ls["low"]:
        errs.append("fast_sale.low exceeds likely_sale.low (a fast sale cannot be worth more than a likely one)")
    if ls and sl and ls["high"] > sl["high"]:
        errs.append("likely_sale.high exceeds suggested_list.high")
    for sx in _strings(doc):
        m = _APPRAISAL_CLAIM.search(sx)
        if m:
            errs.append(f"free text claims an appraisal ({m.group(0)!r}); this is an estimate, not an appraisal")
            break
    return errs


def validate(doc: Any) -> None:
    errs = errors(doc)
    if errs:
        raise ContractViolation("valuation", errs)
