"""E-19: jurisdiction packs + `eligibility(job, packs)` (ADR-0013 §8/§12; START_HERE §12).

Principles (each is tested):
  * NO hard-coded local legal assumption. The evaluator never reasons "outside city limits => no licence"; it knows no
    city, county or state. Everything it concludes is read from a CITED pack.
  * A missing / not-applicable / expired / ambiguous pack is UNKNOWN. UNKNOWN is never "no licence needed".
  * Uncertainty only KEEPS a credential requirement; it can never remove one. Only a fresh, confident, fully resolved,
    authoritative pack that affirmatively finds `credential_required: []` can say eligible without a credential.
  * A stale `date_verified` lowers confidence (and a very old pack is EXPIRED_PACK => UNKNOWN).
  * Sample (`sample: true`) packs are synthetic fixtures: they assert no legal fact and their results are never
    authoritative (`gate()` => ask_michael).
  * The job supplies its own jurisdiction chain (broadest -> most specific). Nothing is geocoded or inferred.

Return value of `eligibility`: {status: eligible|needs_credential|UNKNOWN, authoritative, sample, credential_required,
missing_credentials, confidence, cited{pack_id, jurisdiction, job_class, rule, source, date_verified, permit_notes},
unresolved, reasons[]}.
"""
from __future__ import annotations

import json
import operator
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .ids import parse_ts
from .trust import TrustData, credential_id_problems, validate_claim

OPS = {"gte": operator.ge, "gt": operator.gt, "lte": operator.le, "lt": operator.lt}


class JurisdictionData:
    def __init__(self, directory: str | Path, trust_dir: str | Path | None = None):
        d = Path(directory)
        self.rules = json.loads((d / "jurisdiction_rules.v1.json").read_text("utf-8"))
        self.schema = json.loads((d / "pack.schema.json").read_text("utf-8"))
        self.packs: list[dict] = []
        for f in sorted((d / "packs").glob("*.json")):
            self.packs += json.loads(f.read_text("utf-8"))["packs"]
        self.trust = TrustData(trust_dir or d.parent / "trust")


# ---------------------------------------------------------------- pack validation
def pack_problems(pack: Any, data: JurisdictionData, today: date | None = None) -> list[str]:
    if not isinstance(pack, dict):
        return ["pack must be an object"]
    p = [f"schema:{'/'.join(map(str, e.absolute_path)) or '$'}: {e.message[:120]}"
         for e in Draft202012Validator(data.schema).iter_errors(pack)]
    if p:
        return p
    for cred in pack["credential_required"] or []:
        p += [f"credential {cred!r}: {x}" for x in credential_id_problems(cred, data.trust.credentials)]
        if cred not in data.trust.cred_by_id:
            p.append(f"credential {cred!r} is not in the E-18 vocabulary")
    today = today or datetime.now(timezone.utc).date()
    try:
        dv = date.fromisoformat(pack["date_verified"])
        if dv > today:
            p.append("date_verified is in the future")
    except ValueError:
        p.append("date_verified is not a valid date")
    if pack["sample"]:
        if pack["source"] != "SYNTHETIC-FIXTURE" or not pack["jurisdiction"].upper().startswith("SAMPLE"):
            p.append("a sample pack must use source SYNTHETIC-FIXTURE and a SAMPLE-* jurisdiction")
    else:
        if not pack["source"].lower().startswith(("http://", "https://")) and "citation:" not in pack["source"].lower():
            p.append("a real pack must cite a URL or a 'citation:' source")
        if not pack.get("verified_by"):
            p.append("a real pack needs verified_by")
        if pack["credential_required"] is None and not pack["unresolved"]:
            p.append("credential_required null means unresolved: list what is unresolved")
    if pack["credential_required"] == [] and pack["unresolved"]:
        p.append("a pack with unresolved questions cannot affirm 'no credential required'")
    return p


def data_problems(data: JurisdictionData, today: date | None = None) -> list[str]:
    out, seen = [], set()
    for pk in data.packs:
        out += [f"{pk.get('pack_id')}: {x}" for x in pack_problems(pk, data, today)]
        if pk.get("pack_id") in seen:
            out.append(f"{pk.get('pack_id')}: duplicate pack_id")
        seen.add(pk.get("pack_id"))
    return out


# ---------------------------------------------------------------- the evaluator
def _chain_index(chain: list[str], jurisdiction: str) -> int | None:
    return chain.index(jurisdiction) if jurisdiction in chain else None


def _valid_chain(chain: Any) -> bool:
    if not isinstance(chain, list) or not chain or not all(isinstance(c, str) and c for c in chain):
        return False
    return all(chain[i + 1].startswith(chain[i] + "/") for i in range(len(chain) - 1))


def _unknown(reasons: list[str], **extra: Any) -> dict:
    return {"status": "UNKNOWN", "authoritative": False, "sample": False, "credential_required": None, "missing_credentials": None,
            "confidence": 0.0, "cited": None, "unresolved": [], "reasons": reasons, **extra}


def _age_factor(age_days: int, st: dict) -> float | None:
    if age_days > st["expired_days"]:
        return None
    if age_days > st["stale_days"]:
        return st["very_stale_confidence_factor"]
    if age_days > st["fresh_days"]:
        return st["stale_confidence_factor"]
    return 1.0


def held_credentials(job: dict, chain: list[str], data: JurisdictionData, now: datetime) -> tuple[set[str], list[str]]:
    """Credentials the provider actually holds: claims that pass E-18 validation, are `verified`, unexpired, and (for
    licences) were checked in a jurisdiction of this job's chain. Anything else is ignored with a note."""
    held, notes = set(), []
    for c in job.get("provider_claims") or []:
        probs = validate_claim(c, data.trust)
        if probs:
            notes.append(f"claim {c.get('credential')!r} ignored: {probs[0]}")
            continue
        if c.get("status") != "verified":
            notes.append(f"claim {c.get('credential')!r} is {c.get('status')}")
            continue
        if c.get("expires_at") and parse_ts(c["expires_at"]) <= now:
            notes.append(f"claim {c.get('credential')!r} expired")
            continue
        spec = data.trust.cred_by_id[c["credential"]]
        if spec["requires_jurisdiction"] and c.get("jurisdiction") not in chain:
            notes.append(f"claim {c.get('credential')!r} was checked in {c.get('jurisdiction')!r}, not in this job's jurisdiction")
            continue
        held.add(c["credential"])
    return held, notes


def eligibility(job: dict, packs: list[dict], data: JurisdictionData, now: datetime | None = None) -> dict:
    """`job`: {job_class, jurisdiction_chain:[broadest..most specific], scope:{value_usd?}, provider_claims?:[E-18 claims]}."""
    now = now or datetime.now(timezone.utc)
    if not isinstance(job, dict) or not isinstance(job.get("job_class"), str):
        return _unknown(["BAD_JOB: job_class is required"])
    chain = job.get("jurisdiction_chain")
    if not _valid_chain(chain):
        return _unknown(["NO_JURISDICTION: the job must supply its jurisdiction chain (broadest -> most specific); "
                         "nothing is inferred or geocoded"])
    st, rules = data.rules["staleness"], data.rules
    scope = job.get("scope") or {}
    reasons: list[str] = []
    applicable: list[tuple[int, dict]] = []
    for pk in packs:
        if pack_problems(pk, data, now.date()):
            reasons.append(f"pack {pk.get('pack_id')} ignored: invalid")
            continue
        idx = _chain_index(chain, pk["jurisdiction"])
        if pk["job_class"] != job["job_class"] or idx is None:
            continue
        th = pk.get("threshold")
        if th:
            if th["field"] not in scope:
                return _unknown(reasons + [f"MISSING_JOB_FIELD: pack {pk['pack_id']} depends on scope.{th['field']}, which the job did not state"])
            if not OPS[th["op"]](scope[th["field"]], th["value"]):
                continue
        applicable.append((idx, pk))
    if not applicable:
        return _unknown(reasons + [f"NO_PACK: no pack covers {job['job_class']!r} in {chain[-1]!r} (or any broader jurisdiction on the chain). "
                                   "This is UNKNOWN, not 'no licence needed'"])
    top = max(i for i, _ in applicable)
    best = [pk for i, pk in applicable if i == top]
    outcomes = {json.dumps(sorted(pk["credential_required"]) if pk["credential_required"] is not None else None) for pk in best}
    if len(outcomes) > 1:
        return _unknown(reasons + [f"CONFLICT: {len(best)} packs at {chain[top]!r} disagree: " + ", ".join(pk["pack_id"] for pk in best)])
    pk = best[0]
    age = (now.date() - date.fromisoformat(pk["date_verified"])).days
    factor = _age_factor(age, st)
    cited = {k: pk[k] for k in ("pack_id", "jurisdiction", "job_class", "rule", "source", "date_verified", "permit_notes")}
    base = {"sample": pk["sample"], "authoritative": not pk["sample"], "cited": cited, "unresolved": list(pk["unresolved"])}
    if factor is None:
        return {**_unknown(reasons + [f"EXPIRED_PACK: {pk['pack_id']} was verified {age} days ago (limit {st['expired_days']}); re-verify"]),
                **base, "authoritative": False}
    conf = round(pk["confidence"] * factor, 3)
    if factor < 1.0:
        reasons.append(f"STALE: date_verified {pk['date_verified']} is {age} days old; confidence {pk['confidence']} -> {conf}")
    required = pk["credential_required"]
    if required is None:
        return {**_unknown(reasons + [f"UNRESOLVED: pack {pk['pack_id']} could not determine the requirement"]), **base,
                "confidence": conf, "authoritative": False}
    held, notes = held_credentials(job, chain, data, now)
    reasons += notes
    if required:
        missing = sorted(set(required) - held)
        status = "needs_credential" if missing else "eligible"
        if not missing:
            reasons.append("provider holds every required credential")
        return {**base, "status": status, "credential_required": sorted(required), "missing_credentials": missing, "confidence": conf,
                "reasons": reasons + [f"RULE: {pk['rule']}"]}
    # the pack affirmatively finds no credential required: only a fresh, confident, resolved pack may say so
    if pk["unresolved"] or conf < rules["min_confidence_to_clear"]:
        return {**_unknown(reasons + ["UNCERTAIN: a requirement is never removed on low confidence or open questions"]), **base,
                "confidence": conf, "authoritative": False}
    return {**base, "status": "eligible", "credential_required": [], "missing_credentials": [], "confidence": conf,
            "reasons": reasons + [f"RULE: {pk['rule']}"]}


def gate(result: dict, data: JurisdictionData) -> str:
    """What the rest of the system may do with an eligibility result (data-driven)."""
    g = data.rules["gate"]
    if result["status"] == "UNKNOWN":
        return g["unknown"]
    if not result["authoritative"]:
        return g["non_authoritative"]
    return g["authoritative_eligible"] if result["status"] == "eligible" else g["needs_credential"]
