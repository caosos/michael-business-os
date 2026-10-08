"""Truth-preserving audience views of one canonical inventory object (ADR-0013).

A view may change headline, body, fact order, emphasis and call to action. It may NOT hide or soften a known defect,
change price/terms, upgrade the basis of a fact, drop provenance, or claim verification the inventory does not have.
`lint` is deterministic and structural (plus a short list of contradiction phrases); it is the gate, not trust.
No LLM is involved. Nothing here publishes anything.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .contracts.schemas import ContractViolation, contracts_dir
from .hashing import sha256_of

_RANK = {"UNKNOWN": 0, "seller_stated": 1, "system_inferred": 1, "verified": 2}
# Words that overstate condition when a material defect exists, or claim verification.
_CONDITION_CLAIMS = re.compile(r"\b(like new|mint|flawless|perfect( condition)?|no (issues|problems|defects)|excellent condition|"
                               r"runs (great|perfect(ly)?|like new)|fully (functional|working)|nothing wrong)\b", re.I)
_VERIFY_CLAIMS = re.compile(r"\b(verified|inspected|certified|guaranteed|tested and working)\b", re.I)
_MISLEAD_NEGATION = re.compile(r"\b(no|without|free of)\b[^.]{0,30}\b(smok\w*|leak\w*|rust\w*|damage\w*|issue\w*|problem\w*)\b", re.I)


@lru_cache(maxsize=2)
def _validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(json.loads((contracts_dir() / f"{name}.schema.json").read_text()), format_checker=FormatChecker())


def _schema_errors(name: str, doc: Any) -> list[str]:
    return [f"{name}:{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}" for e in _validator(name).iter_errors(doc)]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def inventory_errors(inv: Any) -> list[str]:
    errs = _schema_errors("inventory", inv)
    if errs:
        return errs
    ids = [f["id"] for f in inv["facts"]] + [d["id"] for d in inv["defects"]]
    if len(ids) != len(set(ids)):
        errs.append("duplicate fact/defect ids")
    for f in inv["facts"]:
        if f["basis"] == "verified" and not f.get("provenance_id"):
            errs.append(f"fact {f['id']}: basis 'verified' requires provenance_id")
        if f["basis"] == "UNKNOWN" and f.get("value") not in ("unknown", "UNKNOWN", None):
            errs.append(f"fact {f['id']}: basis UNKNOWN but a value is given")
    for d in inv["defects"]:
        if d["basis"] == "verified" and not d.get("provenance_id"):
            errs.append(f"defect {d['id']}: basis 'verified' requires provenance_id")
    return errs


def lint(inv: dict, view: dict) -> list[str]:
    """Return the reasons this view is NOT a truthful presentation of `inv` (empty = passes)."""
    errs = inventory_errors(inv) + _schema_errors("merchandising", view)
    if errs:
        return errs
    if view["inventory_id"] != inv["inventory_id"]:
        errs.append("view is for a different inventory object")
    if view["inventory_hash"] != sha256_of(inv):
        errs.append("inventory_hash does not match the inventory this view claims to present (stale or altered)")
    facts = {f["id"]: f for f in inv["facts"]}
    defects = {d["id"]: d for d in inv["defects"]}
    shown = {}
    for sf in view["facts"]:
        f = facts.get(sf["fact_id"])
        if f is None:
            errs.append(f"fact {sf['fact_id']} is not in the inventory (invented)")
            continue
        shown[f["id"]] = sf
        if sf["basis"] != f["basis"]:
            errs.append(f"fact {f['id']}: basis changed {f['basis']} -> {sf['basis']}" + (" (upgrade)" if _RANK[sf["basis"]] > _RANK[f["basis"]] else ""))
        if f.get("provenance_id") and sf.get("provenance_id") != f["provenance_id"]:
            errs.append(f"fact {f['id']}: provenance dropped or changed")
    for f in inv["facts"]:
        if f.get("material") and f["id"] not in shown:
            errs.append(f"material fact {f['id']} ({f['key']}) is not shown")
    disclosed = {}
    for d in view["disclosures"]:
        orig = defects.get(d["defect_id"])
        if orig is None:
            errs.append(f"disclosure {d['defect_id']} is not a known defect (invented)")
        elif _norm(d["text"]) != _norm(orig["text"]):
            errs.append(f"defect {orig['id']} was reworded; disclosures must be verbatim")
        disclosed[d["defect_id"]] = d
    for did in defects:
        if did not in disclosed:
            errs.append(f"defect {did} is not disclosed")
    if view["terms"] != inv["terms"]:
        errs.append("terms differ from the inventory (price/terms may not change per audience)")
    prose = f"{view['headline']}\n{view['body']}\n{view['call_to_action']}"
    if any(d["severity"] == "material" for d in inv["defects"]):
        m = _CONDITION_CLAIMS.search(prose) or _MISLEAD_NEGATION.search(prose)
        if m:
            errs.append(f"prose overstates condition despite a material defect: {m.group(0)!r}")
    if _VERIFY_CLAIMS.search(prose) and not any(f["basis"] == "verified" for f in facts.values()):
        errs.append("prose claims verification but nothing in the inventory is verified")
    for k in (f for f in inv["facts"] if f["basis"] == "UNKNOWN" and f.get("material")):
        if k["id"] in shown and shown[k["id"]]["basis"] != "UNKNOWN":
            errs.append(f"unknown fact {k['id']} presented as known")
    return errs


def validate(inv: dict, view: dict) -> None:
    errs = lint(inv, view)
    if errs:
        raise ContractViolation("merchandising", errs)
