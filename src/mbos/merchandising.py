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

import unicodedata  # noqa: E402

_ZW = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00ad\u200e\u200f"), None)
_HOMO = str.maketrans({"а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y", "к": "k", "м": "m", "н": "h", "т": "t", "і": "i",
                       "ѕ": "s", "ј": "j", "ԁ": "d", "ɡ": "g", "ν": "v", "ο": "o", "ε": "e", "α": "a", "ι": "i", "κ": "k", "ρ": "p",
                       "μ": "m", "η": "n", "τ": "t", "υ": "u", "β": "b", "χ": "x", "ζ": "z", "ѵ": "v", "ө": "o", "в": "b", "п": "n", "г": "r"})
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "!": "i", "|": "l"})


def fold(text: str) -> str:
    """Normalise prose before claim matching: NFKC, strip zero-width/soft-hyphen, fold homoglyphs and leet, collapse whitespace
    (F-59: nbsp, double space, zero-width, leet and Cyrillic look-alikes must not hide a claim). Two spellings are checked (digits kept and folded)."""
    t = unicodedata.normalize("NFKC", text).translate(_ZW).lower().translate(_HOMO)
    t = re.sub(r"[\s\u00a0\u2000-\u200a\u202f\u205f\u3000]+", " ", t)
    return t.strip()


def fold_leet(text: str) -> str:
    return re.sub(r"\s+", " ", fold(text).translate(_LEET)).strip()


_RANK = {"UNKNOWN": 0, "seller_stated": 1, "system_inferred": 1, "verified": 2}
# Words that overstate condition when a material defect exists, or claim verification.
_CONDITION_CLAIMS = re.compile(
    r"\b(like new|mint|flawless|perfect( condition)?|no (issues|problems|defects)|excellent condition|"
    r"runs (great|perfect(ly)?|like new|strong|good|well|fine)|fully (functional|working)|nothing wrong|works (great|fine|perfect(ly)?|well)|"
    r"(good|great) (running|working) (condition|order|shape)|ready to (go|work|mow|use|run|roll)|well (maintained|kept|cared)|"
    r"turn.?key|no (smoke|smoking|leaks?|rust)|just needs? (a |an |some )?(little |small |quick )?(tune.?up|cleaning|carb|adjustment|tweak|love|tlc|service|oil)|"
    r"(only|just) needs|minor (cosmetic|issue|issues|problem|problems|blemish|blemishes|flaw|flaws|quirk|quirks)|"
    r"(easy|simple|quick|small) (fix|repair)|has (some )?(character|quirks?)|runs when it wants|sold as.?is[^.]{0,20}(minor|cosmetic)|"
    r"(cosmetic|minor)[^.]{0,20}(smoke|smoking|leak|noise|knock)|barely (smokes|leaks|knocks)|only (a )?(little|bit|slightly))\b", re.I)
_VERIFY_CLAIMS = re.compile(r"\b(verified|inspected|certified|guaranteed|tested( and working)?|checked out|authenticated)\b", re.I)
_OPERATING_CLAIMS = re.compile(r"\b(tested( and working)?|guaranteed|runs? (great|perfect|well)|works (great|perfect|well)|fully (functional|working))\b", re.I)
_LABELS_CLAIMING_READY = ("Ready to Work",)
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


def revision_errors(old: dict, new: dict) -> list[str]:
    """Inventory truth only moves forward: a defect may not vanish or become less severe, and a fact may not gain a stronger
    basis, unless the evidence for the change is recorded (resolved_defects / provenance). F-61: lowering severity or deleting a
    defect must not be a way to unlock marketing claims."""
    errs, rank = [], {"minor": 0, "material": 1}
    nd = {d["id"]: d for d in new["defects"]}
    resolved = {r["id"] for r in new.get("resolved_defects", [])}
    for d in old["defects"]:
        cur = nd.get(d["id"])
        if cur is None:
            if d["id"] not in resolved:
                errs.append(f"defect {d['id']} was deleted without resolved_defects evidence")
        elif rank[cur["severity"]] < rank[d["severity"]]:
            errs.append(f"defect {d['id']} severity lowered {d['severity']} -> {cur['severity']} (needs a new inventory revision with provenance)")
        elif _norm(cur["text"]) != _norm(d["text"]):
            errs.append(f"defect {d['id']} text was changed")
    of = {f["id"]: f for f in old["facts"]}
    for f in new["facts"]:
        o = of.get(f["id"])
        if o and _RANK[f["basis"]] > _RANK[o["basis"]] and not f.get("provenance_id"):
            errs.append(f"fact {f['id']} basis raised without provenance")
    return errs


def _sentences(text: str) -> list[str]:
    return [x for x in re.split(r"[.!?\n;]+", text) if x.strip()]


def _prose_errors(inv: dict, view: dict, facts: dict) -> list[str]:
    errs: list[str] = []
    head_body = fold(f"{view['headline']} {view['body']}")
    material = [d for d in inv["defects"] if d["severity"] == "material"]
    for d in material:  # (a) the defect must be IN the listing prose, verbatim, not only in a side-field
        if fold(d["text"]) not in head_body:
            errs.append(f"material defect {d['id']} is not stated verbatim in the headline/body: {d['text']!r}")
    variants = [fold(f"{view['headline']}\n{view['body']}\n{view['call_to_action']}"), fold_leet(f"{view['headline']}\n{view['body']}\n{view['call_to_action']}")]
    stripped = []
    for v in variants:
        for d in inv["defects"]:
            v = v.replace(fold(d["text"]), " ").replace(fold_leet(d["text"]), " ")  # the honest statement itself is not an overclaim
        stripped.append(v)
    if material:
        for v in stripped:
            m = _CONDITION_CLAIMS.search(v) or _MISLEAD_NEGATION.search(v)
            if m:
                errs.append(f"prose overstates condition despite a material defect: {m.group(0)!r}")
                break
    verified = [f for f in facts.values() if f["basis"] == "verified"]
    for v in stripped:
        for sent in _sentences(v):
            if _VERIFY_CLAIMS.search(sent):
                words = {w for f in verified for w in re.findall(r"[a-z0-9]{4,}", f"{f['key'].replace('_', ' ')} {f['value']}".lower())}
                if not any(w in sent for w in words):
                    errs.append("prose claims verification of something the inventory does not have verified: " + sent.strip()[:80])
                    break
        if _OPERATING_CLAIMS.search(v) and not any("operat" in f["key"] or "status" in f["key"] for f in verified):
            errs.append("prose makes an operating-condition claim but no operating status is verified")
            break
    return list(dict.fromkeys(errs))


def lint(inv: dict, view: dict, *, baseline: dict | None = None) -> list[str]:
    """Return the reasons this view is NOT a truthful presentation of `inv` (empty = passes). Pass `baseline` (the previously recorded
    inventory revision) to also reject a revision that hides or softens a known defect."""
    errs = inventory_errors(inv) + _schema_errors("merchandising", view)
    if errs:
        return errs
    if baseline is not None:
        errs += revision_errors(baseline, inv)
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
    errs += _prose_errors(inv, view, facts)
    if view.get("label") in _LABELS_CLAIMING_READY and any(d["severity"] == "material" for d in inv["defects"]):
        errs.append(f"label {view['label']!r} claims readiness but a material defect is known")
    for k in (f for f in inv["facts"] if f["basis"] == "UNKNOWN" and f.get("material")):
        if k["id"] in shown and shown[k["id"]]["basis"] != "UNKNOWN":
            errs.append(f"unknown fact {k['id']} presented as known")
    return errs


def validate(inv: dict, view: dict) -> None:
    errs = lint(inv, view)
    if errs:
        raise ContractViolation("merchandising", errs)
