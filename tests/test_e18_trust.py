"""E-18: credential vocabulary, reputation events, penalty ladder, payment boundary (design + validators; nothing granted)."""
from __future__ import annotations

import copy
import json
from datetime import timedelta
from pathlib import Path

import pytest

from mbos_governance import PolicyStore
from mbos_governance.ids import fmt_ts, new_id, utcnow
from mbos_governance.trust import (TrustData, appeal_transition_problems, check_all, credential_id_problems,
                                   payment_boundary_problems, reject_bare_verified, validate_claim, validate_event,
                                   validate_penalty, vocabulary_problems)

REPO = Path(__file__).resolve().parents[1]
TRUST = TrustData(REPO / "policy" / "trust")
SHIPPED = PolicyStore(REPO / "policy" / "policy.v1.json").current().data
NOW = utcnow()


def ts(days=0):
    return fmt_ts(NOW + timedelta(days=days))


def claim(cred="identity_verified", status="verified", **over):
    c = {"claim_id": new_id("clm"), "subject": "user:u1", "credential": cred, "status": status,
         "evidence": [{"kind": "payment_provider_kyc_result", "ref": "kyc:res-1"}],
         "verifier": {"type": "provider", "id": "provider:sample"}, "verified_at": ts(0), "expires_at": ts(365),
         "provenance_ids": [new_id("prov")]}
    c.update(over)
    return c


def event(etype="no_show", subject="user:u1", **over):
    ev = {"event_id": new_id("rev"), "type": etype, "subject": subject, "counterparty": "user:u2", "occurred_at": ts(-3),
          "evidence": [{"kind": "pickup_checkin", "ref": "chk:1"}], "receipt_id": new_id("rcpt"),
          "provenance_ids": [new_id("prov")]}
    ev.update(over)
    return ev


def penalty(step="notice", events=None, **over):
    events = events or [event()]
    p = {"penalty_id": new_id("pen"), "subject": "user:u1", "step": step, "reason_event_ids": [e["event_id"] for e in events],
         "evidence": [{"kind": "receipt", "ref": "rcpt:x"}], "issued_at": ts(0), "effective_from": ts(0),
         "issued_by": {"type": "system", "id": "policy-engine"},
         "appeal": {"state": "none", "window_days": 14, "deadline": ts(14)}, "provenance_ids": [new_id("prov")]}
    p.update(over)
    return p


def index(*evs):
    return {e["event_id"]: e for e in evs}


# ---------------------------------------------------------------- shipped data is sound
def test_shipped_trust_data_passes_every_check():
    assert check_all(TRUST, SHIPPED) == []


# ---------------------------------------------------------------- 'verified' is never bare
@pytest.mark.parametrize("bad", ["verified", "Verified", "is_verified", "fully_verified", "all_verified", "trusted",
                                 "licensed_verified", "general_verified", "certified_verified"])
def test_bare_or_generic_credential_ids_are_rejected(bad):
    assert any("BARE_VERIFIED" in x or "must look like" in x for x in credential_id_problems(bad, TRUST.credentials)), bad


@pytest.mark.parametrize("good", ["identity_verified", "payment_verified", "electrical_license_verified", "insurance_verified"])
def test_specific_credential_ids_pass_the_id_rule(good):
    assert credential_id_problems(good, TRUST.credentials) == []


def test_vocabulary_with_a_bare_entry_is_invalid():
    t = copy.deepcopy(TRUST)
    t.credentials["credentials"].append({"id": "verified", "label": "Verified", "kind": "other", "requires_jurisdiction": False,
                                          "validity_days": None, "evidence_kinds": ["receipt"]})
    assert any("BARE_VERIFIED" in x for x in vocabulary_problems(t))
    t2 = copy.deepcopy(TRUST)
    t2.credentials["credentials"][3]["requires_jurisdiction"] = False       # a licence without a jurisdiction
    assert any("jurisdiction" in x for x in vocabulary_problems(t2))


@pytest.mark.parametrize("obj", [{"verified": True}, {"user": {"is_verified": True}}, {"profile": [{"fully_verified": 1}]},
                                 {"credential": "verified"}, {"badges": ["verified"]}])
def test_bare_verified_keys_and_values_are_rejected(obj):
    assert reject_bare_verified(obj, TRUST.credentials)


def test_claim_with_bare_verified_is_rejected():
    assert any("BARE_VERIFIED" in x for x in validate_claim(claim("verified"), TRUST))
    assert any("BARE_VERIFIED" in x for x in validate_claim({**claim(), "verified": True}, TRUST))


# ---------------------------------------------------------------- credential claims
def test_valid_claims():
    assert validate_claim(claim(), TRUST) == []
    lic = claim("electrical_license_verified", evidence=[{"kind": "regulator_lookup_result", "ref": "lookup:1"}],
                verifier={"type": "regulator_lookup", "id": "lookup:sample"}, jurisdiction="SAMPLE-JURISDICTION")
    assert validate_claim(lic, TRUST) == []
    not_provided = {"claim_id": new_id("clm"), "subject": "user:u1", "credential": "insurance_verified",
                    "status": "not_provided", "provenance_ids": [new_id("prov")]}
    assert validate_claim(not_provided, TRUST) == []        # an honest "not provided" needs no evidence


@pytest.mark.parametrize("over,needle", [
    ({"evidence": []}, "needs evidence"),
    ({"evidence": [{"kind": "selfie", "ref": "x"}]}, "not allowed for identity_verified"),
    ({"verifier": None}, "needs a verifier"),
    ({"expires_at": None}, "expires_at required"),
    ({"expires_at": ts(-1)}, "after verified_at"),
    ({"credential": "ssn_verified"}, "UNKNOWN_CREDENTIAL"),
])
def test_invalid_claims(over, needle):
    c = claim()
    c.update(over)
    if over.get("verifier", 1) is None:
        del c["verifier"]
    assert any(needle in x for x in validate_claim(c, TRUST)), validate_claim(c, TRUST)


def test_licence_needs_jurisdiction_and_not_a_provider():
    lic = claim("plumbing_license_verified", evidence=[{"kind": "regulator_lookup_result", "ref": "l"}])
    probs = validate_claim(lic, TRUST)
    assert any("jurisdiction" in x for x in probs) and any("regulator or a document" in x for x in probs)


# ---------------------------------------------------------------- reputation events are receipted facts with evidence
def test_valid_events():
    assert validate_event(event(), TRUST) == []
    assert validate_event(event("completed_sale", evidence=[{"kind": "receipt", "ref": "r"}]), TRUST) == []
    assert validate_event(event("seller_misrepresentation_finding",
                                evidence=[{"kind": "resolved_dispute", "ref": "d:1"}, {"kind": "photo_set", "ref": "p:1"}]), TRUST) == []


@pytest.mark.parametrize("etype,evidence,needle", [
    ("no_show", [], "schema"),                                                    # no evidence at all (schema minItems)
    ("no_show", [{"kind": "receipt", "ref": "r"}], "needs evidence of one of"),    # wrong kind of evidence
    ("seller_misrepresentation_finding", [{"kind": "resolved_dispute", "ref": "d"}], "corroborating"),   # accusation alone
    ("seller_misrepresentation_finding", [{"kind": "photo_set", "ref": "p"}], "needs evidence of one of"),
    ("made_up_event", [{"kind": "receipt", "ref": "r"}], "UNKNOWN_EVENT_TYPE"),
])
def test_invalid_events(etype, evidence, needle):
    assert any(needle in x for x in validate_event(event(etype, evidence=evidence), TRUST))


def test_event_needs_receipt_provenance_and_counterparty():
    ev = event()
    del ev["receipt_id"]
    assert any("receipt_id" in x for x in validate_event(ev, TRUST))
    ev = event()
    del ev["counterparty"]
    assert any("counterparty" in x for x in validate_event(ev, TRUST))
    ev = event(provenance_ids=[])
    assert any("provenance_ids" in x for x in validate_event(ev, TRUST))


# ---------------------------------------------------------------- penalties: evidence, graduation, human decision, appeal
def test_notice_is_allowed_for_one_event_without_a_human():
    e = event()
    assert validate_penalty(penalty("notice", [e]), index(e), [], TRUST) == []


def test_penalty_without_evidence_is_rejected():
    e = event()
    p = penalty("notice", [e])
    p["evidence"] = []
    assert any("evidence" in x for x in validate_penalty(p, index(e), [], TRUST))
    p = penalty("notice", [e])
    del p["reason_event_ids"]
    assert any("reason_event_ids" in x for x in validate_penalty(p, index(e), [], TRUST))
    p = penalty("notice", [e])
    assert any("EVIDENCE_REQUIRED" in x for x in validate_penalty(p, {}, [], TRUST))             # cites an event nobody recorded
    bad = event(evidence=[{"kind": "receipt", "ref": "r"}])                                      # an event with the wrong evidence
    assert any("invalid" in x for x in validate_penalty(penalty("notice", [bad]), index(bad), [], TRUST))
    pos = event("completed_sale", evidence=[{"kind": "receipt", "ref": "r"}])
    assert any("not a negative event" in x for x in validate_penalty(penalty("notice", [pos]), index(pos), [], TRUST))
    other = event(subject="user:someone-else")
    assert any("not 'user:u1'" in x or "about" in x for x in validate_penalty(penalty("notice", [other]), index(other), [], TRUST))


def test_graduated_no_jump_without_prior_steps():
    evs = [event(), event(), event()]
    big = penalty("suspension", evs, issued_by={"type": "human", "id": "michael"}, decision_approval_id=new_id("appr"),
                  duration_days=30, appeal={"state": "none", "window_days": 30, "deadline": ts(30)}, effective_from=ts(30))
    assert any("GRADUATED" in x for x in validate_penalty(big, index(*evs), [], TRUST))


def test_ladder_climbs_one_step_at_a_time_with_a_human():
    evs = [event(), event()]
    n = penalty("notice", evs[:1])
    assert validate_penalty(n, index(*evs), [], TRUST) == []
    reduction = penalty("score_reduction", evs, issued_by={"type": "human", "id": "michael"}, decision_approval_id=new_id("appr"),
                        reduction_points=5, effective_from=ts(14))
    assert validate_penalty(reduction, index(*evs), [n], TRUST) == []
    assert any("GRADUATED" in x for x in validate_penalty(
        penalty("restriction", evs, issued_by={"type": "human", "id": "michael"}, decision_approval_id=new_id("appr"),
                duration_days=7, effective_from=ts(14)), index(*evs), [n], TRUST))                       # notice -> restriction skips a step


def test_overturned_prior_penalties_do_not_count_for_graduation():
    evs = [event(), event()]
    n = penalty("notice", evs[:1])
    n["appeal"] = {"state": "overturned", "window_days": 14, "deadline": ts(14), "filed_at": ts(1), "reviewer": "michael",
                   "resolved_at": ts(5), "reversal_receipt_id": new_id("rcpt")}
    reduction = penalty("score_reduction", evs, issued_by={"type": "human", "id": "michael"}, decision_approval_id=new_id("appr"),
                        reduction_points=5, effective_from=ts(14))
    assert any("GRADUATED" in x for x in validate_penalty(reduction, index(*evs), [n], TRUST))


@pytest.mark.parametrize("over,needle", [
    ({"decision_approval_id": None}, "human decision"),
    ({"issued_by": {"type": "system", "id": "policy-engine"}}, "must be issued by a human"),
    ({"reduction_points": 11}, "reduction_points"),
    ({"appeal": {"state": "none", "window_days": 3, "deadline": ts(3)}}, "appeal window must be at least"),
    ({"effective_from": ts(1)}, "APPEAL_WINDOW"),
])
def test_score_reduction_rules(over, needle):
    evs = [event(), event()]
    prior = penalty("notice", evs[:1])
    p = penalty("score_reduction", evs, issued_by={"type": "human", "id": "michael"}, decision_approval_id=new_id("appr"),
                reduction_points=5, effective_from=ts(14))
    for k, v in over.items():
        if v is None:
            p.pop(k)
        else:
            p[k] = v
    assert any(needle in x for x in validate_penalty(p, index(*evs), [prior], TRUST)), validate_penalty(p, index(*evs), [prior], TRUST)


def test_needs_enough_underlying_events():
    e = event()
    n = penalty("notice", [e])
    p = penalty("score_reduction", [e], issued_by={"type": "human", "id": "michael"}, decision_approval_id=new_id("appr"),
                reduction_points=5, effective_from=ts(14))
    assert any("at least 2" in x for x in validate_penalty(p, index(e), [n], TRUST))


def test_emergency_exception_only_for_a_resolved_misrepresentation_finding():
    f = event("seller_misrepresentation_finding", evidence=[{"kind": "resolved_dispute", "ref": "d"}, {"kind": "photo_set", "ref": "p"}])
    g = event("seller_misrepresentation_finding", evidence=[{"kind": "resolved_dispute", "ref": "d2"}, {"kind": "photo_set", "ref": "p2"}])
    p = penalty("restriction", [f, g], issued_by={"type": "human", "id": "michael"}, decision_approval_id=new_id("appr"),
                duration_days=7, effective_from=ts(0), emergency={"reason": "active scam pattern"})
    assert validate_penalty(p, index(f, g), [], TRUST) == []                  # skip to rank 2 allowed for this type + emergency
    no_emerg = copy.deepcopy(p)
    del no_emerg["emergency"]
    assert any("APPEAL_WINDOW" in x for x in validate_penalty(no_emerg, index(f, g), [], TRUST))
    a, b = event(), event()
    p2 = penalty("restriction", [a, b], issued_by={"type": "human", "id": "michael"}, decision_approval_id=new_id("appr"),
                 duration_days=7, effective_from=ts(0), emergency={"reason": "x"})
    probs = validate_penalty(p2, index(a, b), [], TRUST)
    assert any("GRADUATED" in x for x in probs) and any("APPEAL_WINDOW" in x for x in probs)


def test_appeal_state_machine_and_resolution_rules():
    assert appeal_transition_problems(TRUST, "none", "filed") == []
    assert appeal_transition_problems(TRUST, "filed", "under_review") == []
    for old, new in (("none", "upheld"), ("filed", "overturned"), ("upheld", "overturned"), ("expired", "filed")):
        assert appeal_transition_problems(TRUST, old, new)
    e = event()
    p = penalty("notice", [e])
    p["appeal"] = {"state": "overturned", "window_days": 14, "deadline": ts(14), "filed_at": ts(1), "reviewer": "someone",
                   "resolved_at": ts(4)}
    assert any("reversal_receipt_id" in x for x in validate_penalty(p, index(e), [], TRUST))
    p["appeal"]["reversal_receipt_id"] = new_id("rcpt")
    assert validate_penalty(p, index(e), [], TRUST) == []
    p["appeal"]["reviewer"] = "policy-engine"                                     # same as issuer
    assert any("reviewer must differ" in x for x in validate_penalty(p, index(e), [], TRUST))


def test_no_appeal_after_the_deadline_must_be_expired():
    e = event()
    p = penalty("notice", [e], appeal={"state": "none", "window_days": 14, "deadline": ts(14)})
    assert validate_penalty(p, index(e), [], TRUST, now=NOW + timedelta(days=15)) != []
    p["appeal"]["state"] = "expired"
    assert validate_penalty(p, index(e), [], TRUST, now=NOW + timedelta(days=15)) == []


# ---------------------------------------------------------------- payment boundary grants nothing
def test_shipped_boundary_is_clean_and_nobody_holds_money_payment():
    assert payment_boundary_problems(TRUST.payment, SHIPPED) == []
    assert not [c for grants in SHIPPED["agent_grants"].values() for c in grants if c.startswith("money.payment.")]
    assert all(op["granted_to"] == [] and op["tier"] == 0 and op["step_up_required"] for op in TRUST.payment["operations"])
    assert {o["id"] for o in TRUST.payment["operations"]} == {"authorize", "release_authorization", "capture", "refund", "payout"}


@pytest.mark.parametrize("mutate,needle", [
    (lambda s: s["operations"][0].__setitem__("granted_to", ["agent-01-coordinator"]), "granted_to must be []"),
    (lambda s: s["controls"].__setitem__("granted_to_nobody", False), "granted_to_nobody"),
    (lambda s: s["provider"].__setitem__("selected", "SomePay"), "no provider may be selected"),
    (lambda s: s.__setitem__("status", "LIVE"), "SPEC_ONLY_NOT_BUILT"),
    (lambda s: s["operations"][2].__setitem__("reversibility", "reversible"), "capture must be classified irreversible"),
    (lambda s: s["operations"][1].__setitem__("step_up_required", False), "step-up required"),
    (lambda s: s["operations"][0].__setitem__("capability", "money.transfer.send"), "namespace"),
])
def test_payment_boundary_mutations_are_caught(mutate, needle):
    spec = copy.deepcopy(TRUST.payment)
    mutate(spec)
    assert any(needle in x for x in payment_boundary_problems(spec, SHIPPED)), payment_boundary_problems(spec, SHIPPED)


def test_policy_granting_a_payment_capability_is_caught():
    pol = copy.deepcopy(SHIPPED)
    pol["capabilities"]["money.payment.capture"] = {"category": "money", "effector": "dryrun"}
    pol["agent_grants"]["agent-01-coordinator"].append("money.payment.capture")
    assert any("granted to nobody" in x for x in payment_boundary_problems(TRUST.payment, pol))
    pol2 = copy.deepcopy(SHIPPED)
    pol2["capabilities"]["money.payment.capture"] = {"category": "purchase", "effector": "dryrun"}
    assert any("category money" in x for x in payment_boundary_problems(TRUST.payment, pol2))


def test_no_capability_is_granted_by_this_task():
    """E-18 adds no capability to the running policy."""
    assert not [c for c in SHIPPED["capabilities"] if c.startswith(("money.payment.authorize", "money.payment.capture",
                                                                   "money.payment.refund", "money.payment.payout", "money.payment.release"))]


def test_cli_trust_check(env, capsys):
    from mbos_governance.cli import main
    assert main(["--policy", str(REPO / "policy/policy.v1.json"), "trust", "check"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
