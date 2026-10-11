"""Value-free schema and validation of an owner-local decision case (A-61/A-64). Split from decision_cases.py to keep files short."""

from __future__ import annotations

from datetime import datetime
from typing import Any

DECISIONS = ("pass", "watch", "pursue")
PROVENANCE = ("verified", "owner_estimate", "unverified")
EVIDENCE_KINDS = ("condition", "photo", "dimensions", "capacity", "paperwork", "cost", "sold_comparable", "repair_work", "other")
CASE_KEYS = {"listing_id", "source", "title", "decided_at", "decision", "reason_summary", "evidence", "owner_estimates", "alternatives_considered",
             "uncertainty", "missing_evidence", "owner_skills", "category_tags", "outcome"}
MAX_TEXT = 4000
KINDS = ("case", "correction", "outcome", "reset", "enable", "disable")


class CaseError(ValueError):
    pass




def _s(v: Any, name: str, required: bool = True) -> str:
    if v is None or v == "":
        if required:
            raise CaseError(f"{name} is required")
        return ""
    if not isinstance(v, str) or len(v) > MAX_TEXT:
        raise CaseError(f"{name} must be text of at most {MAX_TEXT} characters")
    return v.strip()


def _list(v: Any, name: str) -> list:
    if v in (None, ""):
        return []
    if not isinstance(v, list):
        raise CaseError(f"{name} must be a list")
    return v


def validate_case(c: Any, *, partial: bool = False) -> dict:
    """A complete case, or (partial=True) only the fields a correction changes. Owner estimates can never be labelled verified."""
    if not isinstance(c, dict):
        raise CaseError("a case must be a JSON object")
    extra = set(c) - CASE_KEYS
    if extra:
        raise CaseError(f"unknown fields: {sorted(extra)}")
    out: dict = {}
    for k in ("listing_id", "source", "reason_summary"):
        if k in c or not partial:
            out[k] = _s(c.get(k), k)
    for k in ("title", "owner_skills"):
        if k in c:
            out[k] = _s(c[k], k, False)
    if "decided_at" in c or not partial:
        out["decided_at"] = _s(c.get("decided_at"), "decided_at")
        try:
            datetime.fromisoformat(out["decided_at"].replace("Z", "+00:00"))
        except ValueError:
            raise CaseError("decided_at must be an ISO 8601 time")
    if "decision" in c or not partial:
        if c.get("decision") not in DECISIONS:
            raise CaseError(f"decision must be one of {DECISIONS}")
        out["decision"] = c["decision"]
    if "evidence" in c or not partial:
        ev = _list(c.get("evidence"), "evidence")
        if not ev and not partial:
            raise CaseError("evidence needs at least one entry (kind, text, provenance)")
        out["evidence"] = []
        for e in ev:
            if not isinstance(e, dict) or e.get("kind") not in EVIDENCE_KINDS or e.get("provenance") not in PROVENANCE:
                raise CaseError(f"each evidence entry needs kind in {EVIDENCE_KINDS} and provenance in {PROVENANCE}")
            out["evidence"].append({"kind": e["kind"], "text": _s(e.get("text"), "evidence text"), "provenance": e["provenance"]})
    if "owner_estimates" in c:
        out["owner_estimates"] = []
        for e in _list(c["owner_estimates"], "owner_estimates"):
            if not isinstance(e, dict) or e.get("provenance", "owner_estimate") != "owner_estimate":
                raise CaseError("an owner estimate is always labelled owner_estimate, never verified")
            amt = e.get("amount_usd")
            if amt is not None and (isinstance(amt, bool) or not isinstance(amt, (int, float)) or amt != amt or amt in (float("inf"), float("-inf"))):
                raise CaseError("amount_usd must be a finite number or absent")
            out["owner_estimates"].append({"label": _s(e.get("label"), "estimate label"), "amount_usd": amt, "note": _s(e.get("note"), "estimate note", False),
                                           "provenance": "owner_estimate"})
    for k in ("alternatives_considered", "uncertainty", "missing_evidence", "category_tags"):
        if k in c:
            out[k] = [_s(x, k) for x in _list(c[k], k)]
    if "outcome" in c:
        if c["outcome"] not in (None, ""):
            raise CaseError("an outcome is recorded later with the `outcome` command, not at import")
    return out


TEXT_TEMPLATE = """# Decision case: fill in the values after each colon. Lines starting with # are ignored. One value per line; repeat a line to add more.
# Keep this file OUTSIDE the repo (for example in your home folder). Nothing here goes to GitHub.
listing_id:
source: gsa
title:
decided_at: 2026-01-01T12:00:00Z
decision: pass            # pass | watch | pursue
reason: 
# evidence: kind | provenance | what you knew then.   kind: condition photo dimensions capacity paperwork cost sold_comparable repair_work other
#           provenance: verified | owner_estimate | unverified
evidence: condition | verified | 
evidence: cost | owner_estimate | 
# estimate: label | amount in dollars (or leave empty) | basis
estimate: 
alternative: 
uncertainty: 
missing: 
skills: 
tags: trailer, 
"""

_REPEAT = {"evidence", "estimate", "alternative", "uncertainty", "missing", "tags"}


def parse_text(text: str) -> dict:
    """The plain-text form -> a case dict (not yet validated). Empty values are skipped; `tags` takes a comma list."""
    case: dict = {"evidence": [], "owner_estimates": [], "alternatives_considered": [], "uncertainty": [], "missing_evidence": [], "category_tags": []}
    names = {"reason": "reason_summary", "skills": "owner_skills"}
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.split("  #", 1)[0].strip() if "  #" in raw else raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, val = line.partition(":")
        key, val = key.strip().lower(), val.strip()
        if not sep:
            raise CaseError(f"line {n}: expected 'name: value'")
        if key not in names and key not in _REPEAT and key not in ("listing_id", "source", "title", "decided_at", "decision"):
            raise CaseError(f"line {n}: unknown field {key!r}")
        if not val:
            continue
        if key == "evidence":
            parts = [x.strip() for x in val.split("|", 2)]
            if len(parts) != 3 or not parts[2]:
                if len(parts) == 3:
                    continue                                   # a template line left blank
                raise CaseError(f"line {n}: evidence needs 'kind | provenance | text'")
            case["evidence"].append({"kind": parts[0], "provenance": parts[1], "text": parts[2]})
        elif key == "estimate":
            parts = [x.strip() for x in val.split("|", 2)] + ["", ""]
            amt = None
            if parts[1]:
                try:
                    amt = float(parts[1].replace("$", "").replace(",", ""))
                except ValueError:
                    raise CaseError(f"line {n}: the estimate amount must be a number or empty")
            case["owner_estimates"].append({"label": parts[0], "amount_usd": amt, "note": parts[2]})
        elif key == "alternative":
            case["alternatives_considered"].append(val)
        elif key == "uncertainty":
            case["uncertainty"].append(val)
        elif key == "missing":
            case["missing_evidence"].append(val)
        elif key == "tags":
            case["category_tags"] += [t.strip() for t in val.split(",") if t.strip()]
        else:
            case[names.get(key, key)] = val
    return case
