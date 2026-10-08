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


def errors(doc: Any) -> list[str]:
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
    if known and doc["confidence"] == "high" and not any(e["kind"] in ("sold_comp", "record") for e in doc["evidence"]):
        errs.append("confidence high requires sold comps or a record, not asking comps/priors alone")
    return errs


def validate(doc: Any) -> None:
    errs = errors(doc)
    if errs:
        raise ContractViolation("valuation", errs)
