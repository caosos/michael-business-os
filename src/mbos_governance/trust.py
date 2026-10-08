"""E-18: trust seams (ADR-0013 §8) — credential vocabulary, reputation events, penalty ladder, payment boundary.

DESIGN + VALIDATORS ONLY. Nothing here grants a capability, calls a provider, applies a penalty to a real user or
asserts a legal fact. Data lives in policy/trust/*.json; record shapes in policy/trust/schemas/*.schema.json.

Rules enforced by code (a JSON schema cannot express them):
  * the bare word "verified" is invalid as a credential, a key name or a badge — credentials are `<specific>_verified`;
  * a `verified` claim needs evidence, a verifier, verified_at, an expiry when the vocabulary has a validity, and a
    jurisdiction for licences; evidence kinds must be ones the vocabulary allows for THAT credential;
  * a reputation event is a receipted fact: evidence of a kind its type requires, a receipt id, provenance;
  * a penalty needs evidence AND enough underlying negative events, is GRADUATED (one step at a time, a skip only for
    types the data allows), needs a human decision above `notice`, takes effect only after its appeal window (unless
    the data-allowed emergency exception applies), and an overturned appeal requires a reversal receipt;
  * the payment boundary grants nothing: every `money.payment.*` operation is `granted_to: []`, and no agent in the
    running policy holds any `money.payment.*` capability.
Every validator returns a list of problem strings ([] = valid). They never raise on bad input (fail closed = invalid).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from importlib import resources  # noqa: F401  (kept for parity with other modules)
from pathlib import Path
from typing import Any, Protocol

from jsonschema import Draft202012Validator

from .ids import parse_ts

CRED_ID = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*_verified$")
APPEAL_OK = {"none": ["filed", "expired"], "filed": ["under_review"], "under_review": ["upheld", "overturned"],
             "upheld": [], "overturned": [], "expired": []}


class TrustData:
    """The three data files + the record schemas, loaded from a directory (default: policy/trust)."""

    def __init__(self, directory: str | Path):
        d = Path(directory)
        self.credentials = json.loads((d / "credentials.v1.json").read_text("utf-8"))
        self.reputation = json.loads((d / "reputation.v1.json").read_text("utf-8"))
        self.payment = json.loads((d / "payment_boundary.v1.json").read_text("utf-8"))
        self.schemas = {n: json.loads((d / "schemas" / f"{n}.schema.json").read_text("utf-8"))
                        for n in ("credential-claim", "reputation-event", "penalty")}

    @property
    def cred_by_id(self) -> dict[str, dict]:
        return {c["id"]: c for c in self.credentials["credentials"]}

    @property
    def event_by_id(self) -> dict[str, dict]:
        return {e["id"]: e for e in self.reputation["event_types"]}

    @property
    def ladder(self) -> list[dict]:
        return sorted(self.reputation["penalty_ladder"]["steps"], key=lambda s: s["rank"])


def _schema_problems(schema: dict, obj: Any) -> list[str]:
    return [f"schema:{'/'.join(map(str, e.absolute_path)) or '$'}: {e.message[:140]}"
            for e in Draft202012Validator(schema).iter_errors(obj)]


def _walk_keys(obj: Any, depth: int = 0):
    if depth > 8:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _walk_keys(v, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_keys(v, depth + 1)


# ---------------------------------------------------------------- vocabulary
def credential_id_problems(cred_id: Any, vocab: dict) -> list[str]:
    if not isinstance(cred_id, str):
        return ["credential id must be a string"]
    if cred_id.lower() in {w.lower() for w in vocab["reserved_bare_words"]}:
        return [f"BARE_VERIFIED: {cred_id!r} is not a credential; name WHICH credential (e.g. identity_verified)"]
    if not CRED_ID.match(cred_id):
        return [f"credential id {cred_id!r} must look like <specific>_verified"]
    qualifiers = set(cred_id[: -len("_verified")].split("_"))
    if qualifiers <= {q.lower() for q in vocab["generic_qualifiers"]}:
        return [f"BARE_VERIFIED: {cred_id!r} is generic ({', '.join(sorted(qualifiers))}); it would imply every credential"]
    return []


def vocabulary_problems(trust: TrustData) -> list[str]:
    """The shipped vocabulary must itself obey its rules."""
    v, p, seen = trust.credentials, [], set()
    for c in v["credentials"]:
        p += [f"{c.get('id')}: {x}" for x in credential_id_problems(c.get("id"), v)]
        if c["id"] in seen:
            p.append(f"{c['id']}: duplicate")
        seen.add(c["id"])
        if not c.get("evidence_kinds"):
            p.append(f"{c['id']}: no evidence kinds (a credential must be provable)")
        if c["kind"] == "license" and not c.get("requires_jurisdiction"):
            p.append(f"{c['id']}: a licence credential must require a jurisdiction")
    for key in _walk_keys(v["credentials"]):
        if str(key).lower() in {w.lower() for w in v["reserved_bare_words"]}:
            p.append(f"vocabulary uses the reserved bare key {key!r}")
    return p


# ---------------------------------------------------------------- credential claims
def reject_bare_verified(obj: Any, vocab: dict) -> list[str]:
    """Any key named like a bare 'verified' flag, or a credential field holding the bare word."""
    bare = {w.lower() for w in vocab["reserved_bare_words"]}
    p = [f"BARE_VERIFIED: key {k!r} is invalid; use a specific <credential>_verified status" for k in _walk_keys(obj)
         if str(k).lower() in bare]
    if isinstance(obj, dict):
        for field in ("credential", "credentials", "badge", "badges"):
            val = obj.get(field)
            for v in (val if isinstance(val, list) else [val]):
                if isinstance(v, str) and v.lower() in bare:
                    p.append(f"BARE_VERIFIED: {field}={v!r}")
    return p


def validate_claim(claim: Any, trust: TrustData) -> list[str]:
    if not isinstance(claim, dict):
        return ["claim must be an object"]
    vocab = trust.credentials
    p = reject_bare_verified(claim, vocab)
    p += _schema_problems(trust.schemas["credential-claim"], claim)
    cid = claim.get("credential")
    p += credential_id_problems(cid, vocab)
    cred = trust.cred_by_id.get(cid) if isinstance(cid, str) else None
    if cred is None:
        if not p or all(not x.startswith("BARE_VERIFIED") for x in p):
            p.append(f"UNKNOWN_CREDENTIAL: {cid!r} is not in the vocabulary")
        return p
    if claim.get("status") == "verified":
        ev, ver = claim.get("evidence") or [], claim.get("verifier")
        if not ev:
            p.append("verified claim needs evidence")
        bad = [e.get("kind") for e in ev if e.get("kind") not in cred["evidence_kinds"]]
        if bad:
            p.append(f"evidence kinds {bad} are not allowed for {cid} (allowed: {cred['evidence_kinds']})")
        if not ver:
            p.append("verified claim needs a verifier")
        if not claim.get("verified_at"):
            p.append("verified claim needs verified_at")
        if cred.get("validity_days") and not claim.get("expires_at"):
            p.append(f"{cid} has a validity period: expires_at required")
        try:
            if claim.get("expires_at") and claim.get("verified_at") and parse_ts(claim["expires_at"]) <= parse_ts(claim["verified_at"]):
                p.append("expires_at must be after verified_at")
        except ValueError as exc:
            p.append(f"bad timestamp: {exc}")
    if cred.get("requires_jurisdiction") and claim.get("status") == "verified" and not claim.get("jurisdiction"):
        p.append(f"{cid} is a licence: the jurisdiction it was checked in is required")
    if claim.get("status") == "verified" and cred["kind"] == "license" and claim.get("verifier", {}).get("type") == "provider":
        p.append("a licence is checked against the regulator or a document, not by a payment provider")
    return p


# ---------------------------------------------------------------- reputation events
def validate_event(event: Any, trust: TrustData) -> list[str]:
    if not isinstance(event, dict):
        return ["event must be an object"]
    p = reject_bare_verified(event, trust.credentials) + _schema_problems(trust.schemas["reputation-event"], event)
    spec = trust.event_by_id.get(event.get("type"))
    if spec is None:
        return p + [f"UNKNOWN_EVENT_TYPE: {event.get('type')!r}"]
    kinds = {e.get("kind") for e in (event.get("evidence") or [])}
    if not kinds:
        p.append("EVIDENCE_REQUIRED: a reputation event is a fact with evidence")
    elif not kinds & set(spec["requires_evidence"]):
        p.append(f"{spec['id']} needs evidence of one of {spec['requires_evidence']}, got {sorted(kinds)}")
    if spec.get("also_requires") and not kinds & set(spec["also_requires"]):
        p.append(f"{spec['id']} also needs corroborating evidence of one of {spec['also_requires']}")
    if spec["requires_counterparty"] and not event.get("counterparty"):
        p.append(f"{spec['id']} needs a counterparty")
    unknown = kinds - set(trust.reputation["evidence_kinds"])
    if unknown:
        p.append(f"unknown evidence kinds {sorted(unknown)}")
    return p


# ---------------------------------------------------------------- penalties
def validate_penalty(penalty: Any, events: dict[str, dict], prior_penalties: list[dict], trust: TrustData,
                     now: datetime | None = None) -> list[str]:
    """`events`: event_id -> event (the ones the penalty cites must be here and valid). `prior_penalties`: the subject's
    earlier penalties that were NOT overturned (the graduated history)."""
    if not isinstance(penalty, dict):
        return ["penalty must be an object"]
    p = _schema_problems(trust.schemas["penalty"], penalty)
    if p:
        return p
    cfg, ladder = trust.reputation["penalty_ladder"], trust.ladder
    step = next((s for s in ladder if s["id"] == penalty["step"]), None)
    if step is None:
        return [f"unknown step {penalty['step']!r}"]
    # evidence-based
    cited = []
    for eid in penalty["reason_event_ids"]:
        ev = events.get(eid)
        if ev is None:
            p.append(f"EVIDENCE_REQUIRED: reason event {eid} is not a known receipted event")
            continue
        bad = validate_event(ev, trust)
        if bad:
            p.append(f"reason event {eid} is invalid: {bad[0]}")
        if ev.get("subject") != penalty["subject"]:
            p.append(f"reason event {eid} is about {ev.get('subject')!r}, not {penalty['subject']!r}")
        if trust.event_by_id.get(ev.get("type"), {}).get("polarity") != "negative":
            p.append(f"reason event {eid} is not a negative event")
        cited.append(ev)
    if len(cited) < step["min_negative_events"]:
        p.append(f"{step['id']} needs at least {step['min_negative_events']} valid negative events, got {len(cited)}")
    # graduated
    prior_ranks = [next(s["rank"] for s in ladder if s["id"] == q["step"]) for q in prior_penalties
                   if q.get("subject") == penalty["subject"] and q.get("appeal", {}).get("state") != "overturned"]
    top_prior = max(prior_ranks, default=-1)
    if cfg["one_step_at_a_time"] and step["rank"] > top_prior + 1:
        allowed_skip = max([cfg["max_rank_without_prior_step"].get(e.get("type"), cfg["max_rank_without_prior_step"]["default"])
                            for e in cited] or [cfg["max_rank_without_prior_step"]["default"]])
        if step["rank"] > max(top_prior + 1, allowed_skip):
            p.append(f"GRADUATED: cannot go to {step['id']} (rank {step['rank']}) from rank {top_prior}; "
                     f"one step at a time (a skip is allowed only to rank {allowed_skip} for the cited event types)")
    # human decision
    if step["requires_human_decision"]:
        if not penalty.get("decision_approval_id"):
            p.append(f"{step['id']} needs a human decision (decision_approval_id): models may only propose")
        if penalty["issued_by"]["type"] != "human":
            p.append(f"{step['id']} must be issued by a human, not {penalty['issued_by']['type']}")
    # bounds
    if step["id"] == "score_reduction" and not 1 <= penalty.get("reduction_points", 0) <= step["max_reduction_points"]:
        p.append(f"score_reduction needs 1..{step['max_reduction_points']} reduction_points")
    if "max_duration_days" in step and step["id"] in ("restriction", "suspension"):
        if not 1 <= penalty.get("duration_days", 0) <= step["max_duration_days"]:
            p.append(f"{step['id']} needs duration_days 1..{step['max_duration_days']}")
    # appeal
    ap = penalty["appeal"]
    if ap["window_days"] < step["appeal_window_days"]:
        p.append(f"appeal window must be at least {step['appeal_window_days']} days for {step['id']}")
    try:
        issued, deadline, eff = parse_ts(penalty["issued_at"]), parse_ts(penalty["appeal"]["deadline"]), parse_ts(penalty["effective_from"])
        if deadline < issued + timedelta(days=ap["window_days"]):
            p.append("appeal deadline is earlier than issued_at + window_days")
        emergency = penalty.get("emergency")
        if step["rank"] > 0 and cfg["takes_effect_after_appeal_window"] and eff < deadline:
            ex = cfg["emergency_exception"]
            ok = (emergency and step["rank"] <= ex["max_rank"] and penalty.get("decision_approval_id")
                  and any(e.get("type") in ex["allowed_event_types"] and
                          {x.get("kind") for x in e.get("evidence", [])} & set(ex["requires_evidence_kinds"]) for e in cited))
            if not ok:
                p.append("APPEAL_WINDOW: a penalty above notice takes effect only after its appeal deadline "
                         "(emergency exception needs an allowed event type, resolved-dispute evidence, rank <= "
                         f"{ex['max_rank']} and a human decision)")
        elif emergency and step["rank"] == 0:
            p.append("emergency is meaningless for a notice")
        if now is not None and ap["state"] == "none" and now > deadline:
            p.append("appeal state 'none' after the deadline must be 'expired'")
    except ValueError as exc:
        p.append(f"bad timestamp: {exc}")
    if ap["state"] == "overturned" and not ap.get("reversal_receipt_id"):
        p.append("an overturned appeal requires reversal_receipt_id (the penalty must be reversed, receipted)")
    if ap["state"] in ("upheld", "overturned"):
        if not ap.get("reviewer"):
            p.append("a resolved appeal needs a reviewer")
        elif cfg and trust.reputation["appeal"]["reviewer_must_differ_from_issuer"] and ap["reviewer"] == penalty["issued_by"]["id"]:
            p.append("the appeal reviewer must differ from the issuer")
        if not ap.get("resolved_at"):
            p.append("a resolved appeal needs resolved_at")
    if ap["state"] in ("filed", "under_review", "upheld", "overturned") and not ap.get("filed_at"):
        p.append("a filed appeal needs filed_at")
    return p


def appeal_transition_problems(trust: TrustData, old: str, new: str) -> list[str]:
    table = trust.reputation["appeal"]["transitions"]
    return [] if new in table.get(old, []) else [f"illegal appeal transition {old} -> {new}"]


# ---------------------------------------------------------------- payment boundary
class PaymentProvider(Protocol):
    """The replaceable provider boundary (SPEC ONLY — no implementation exists, none is granted, none is chosen).

    Every method takes an idempotency key and integer MINOR units; returns a durable provider event id. Calls are made
    only by the Action Gateway's effector after guard checks G1-G8 (never by an agent), dry-run until Michael decides
    otherwise. `lookup` answers "did this idempotency key land?" so crashed calls are reconciled, never resent."""

    def authorize(self, *, idempotency_key: str, amount_minor: int, currency: str, payer_ref: str, reference: str) -> dict: ...
    def release_authorization(self, *, idempotency_key: str, authorization_ref: str) -> dict: ...
    def capture(self, *, idempotency_key: str, authorization_ref: str, amount_minor: int) -> dict: ...
    def refund(self, *, idempotency_key: str, capture_ref: str, amount_minor: int) -> dict: ...
    def payout(self, *, idempotency_key: str, payee_ref: str, amount_minor: int, currency: str, reference: str) -> dict: ...
    def lookup(self, *, idempotency_key: str) -> dict | None: ...


def payment_boundary_problems(spec: dict, policy_data: dict | None = None) -> list[str]:
    p: list[str] = []
    ns = spec["controls"]["namespace"]
    if not spec["controls"].get("granted_to_nobody"):
        p.append("controls.granted_to_nobody must be true")
    if spec.get("status") != "SPEC_ONLY_NOT_BUILT":
        p.append("payment boundary status must stay SPEC_ONLY_NOT_BUILT until a separate Michael decision")
    if spec["provider"].get("selected") is not None:
        p.append("no provider may be selected in the spec (UNKNOWN; Michael + legal decision)")
    if spec.get("amount_unit", "").startswith("integer") is False:
        p.append("amounts must be integer minor units")
    for op in spec["operations"]:
        if not op["capability"].startswith(ns):
            p.append(f"{op['id']}: capability must be in the {ns} namespace")
        if op["granted_to"]:
            p.append(f"{op['id']}: granted_to must be [] (money.payment.* is granted to nobody), got {op['granted_to']}")
        if op["tier"] != 0 or not op["step_up_required"] or not op["idempotency_key_required"]:
            p.append(f"{op['id']}: must be tier 0, step-up required, idempotency key required")
    kinds = {o["id"]: o["reversibility"] for o in spec["operations"]}
    for name in ("capture", "payout"):
        if kinds.get(name) != "irreversible":
            p.append(f"{name} must be classified irreversible")
    if policy_data is not None:
        caps = policy_data.get("capabilities", {})
        for cap, c in caps.items():
            if cap.startswith(ns) and c["category"] != "money":
                p.append(f"policy capability {cap} must be category money")
        for agent, granted in policy_data.get("agent_grants", {}).items():
            held = [g for g in granted if g.startswith(ns)]
            if held:
                p.append(f"agent {agent} holds {held}: money.payment.* is granted to nobody")
    return p


def check_all(trust: TrustData, policy_data: dict | None = None) -> list[str]:
    return vocabulary_problems(trust) + payment_boundary_problems(trust.payment, policy_data)
