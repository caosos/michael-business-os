"""G-11: adversarial acceptance of the Deal Sniffer product seams (ADR-0013), pure functions from the pinned `mbos`:
merchandising lint (`mbos.merchandising`), mission/ledger/plan (`mbos.mission`), campaign (`mbos.campaign`), valuation
(`mbos.valuation`). Positive controls pin what must stay rejected; strict xfails are tied to F-59..F-68 (owner 01)."""
from __future__ import annotations

import copy
import json
import pathlib

import pytest

from mbos import campaign, mission, valuation
from mbos import merchandising as mer
from mbos.hashing import sha256_of

EX = pathlib.Path(__file__).resolve().parents[2] / "ext" / "seams"
NAN, INF = float("nan"), float("inf")
PROV = "prov_01J9Z0000000000000000000AA"


def residual(reason):
    """G-12: the owner fix closed the other cases of this finding; only this case stays a strict xfail."""
    return pytest.mark.xfail(strict=True, reason=reason)


def load(name):
    return json.loads((EX / name).read_text())


INV, VIEW = load("inventory--mower.example.json"), load("inventory--mower-view-mechanic.example.json")
PLAN, LEDGER = load("mission--mission-plan.example.json"), load("mission--capital-ledger.example.json")
CAMP, VAL = load("campaign--trailer-wanted.example.json"), load("valuation--mower.example.json")


def lint(view_f=None, inv_f=None, view=None):
    inv = copy.deepcopy(INV)
    if inv_f:
        inv_f(inv)
    v = copy.deepcopy(view or VIEW)
    v["inventory_hash"] = sha256_of(inv)
    if view_f:
        view_f(v)
    return mer.lint(inv, v)


def setf(field, text):
    return lambda v: v.__setitem__(field, text)


# ------------------------------------------------------------------ controls: the examples are valid
def test_all_example_views_pass_and_all_examples_validate():
    for f in sorted(EX.glob("inventory--mower-view-*.json")):
        assert mer.lint(INV, load(f.name)) == [], f.name
    assert mission.plan_errors(PLAN) == [] and mission.ledger_errors(LEDGER) == []
    assert campaign.errors(CAMP) == [] and valuation.errors(VAL) == []


# ------------------------------------------------------------------ merchandising: what the lint DOES catch (must keep catching)
@pytest.mark.parametrize("name,f", [
    ("price-changed", lambda v: v["terms"].update(price_usd=300)), ("terms-key-added", lambda v: v["terms"].update(financing="available")),
    ("basis-upgraded", lambda v: v["facts"][0].update(basis="verified")), ("unknown-shown-as-known", lambda v: v["facts"][2].update(basis="seller_stated")),
    ("defect-omitted", lambda v: v.__setitem__("disclosures", [])), ("defect-reworded", lambda v: v["disclosures"][0].update(text="Engine has some smoke")),
    ("defect-homoglyph", lambda v: v["disclosures"][0].update(text="Еngine smokes blue under load")),
    ("defect-zero-width", lambda v: v["disclosures"][0].update(text="Engine smokes blue​ under load")),
    ("invented-fact", lambda v: v["facts"].append({"fact_id": "f99", "basis": "verified"})),
    ("material-fact-hidden", lambda v: v["facts"].pop(0)),
    ("like-new-in-headline", setf("headline", "Like new Brand X 42T riding mower")), ("runs-great-in-cta", setf("call_to_action", "Runs great, buy now")),
    ("no-smoke", setf("body", "No smoke at idle.")), ("verification-claim", setf("body", "Inspected by a local shop.")),
    ("other-inventory", lambda v: v.__setitem__("inventory_id", "inv_01J9Z00000000000000000AAAA".replace("AAAA", "M0WS"))),
    ("stale-hash", lambda v: v.__setitem__("inventory_hash", "sha256:" + "0" * 64))])
def test_the_lint_catches_these_untruthful_views(name, f):
    inv = copy.deepcopy(INV)
    v = copy.deepcopy(VIEW)
    v["inventory_hash"] = sha256_of(inv)
    f(v)
    if name == "stale-hash":
        v["inventory_hash"] = "sha256:" + "0" * 64
    assert mer.lint(inv, v), f"{name} slipped through"


def test_a_view_may_reorder_emphasise_and_rewrite_prose_truthfully():
    assert lint(lambda v: (v["facts"].reverse(), v["facts"][0].update(emphasis=True), v.__setitem__("headline", "Mower for a mechanic"),
                           v.__setitem__("body", "Runs, but the engine smokes blue under load. Priced to leave room for the work."))) == []


# ------------------------------------------------------------------ merchandising: bypasses (strict xfails)
EUPHEMISMS = ["Runs when it wants to. Sold as is, minor cosmetic smoke.", "Starts and mows. Small amount of exhaust haze, normal for the age.",
              "Strong runner, just needs a tune-up.", "Great little mower, zero complaints from me.", "Not a single problem in my use.",
              "Nothing to disclose beyond normal wear.", "Runs excellent.", "Runs like a top.", "In very good shape.",
              "Does not smoke at idle, cold or hot.", "never leaked, never overheated", "Tested and running well.", "Pre-purchase inspection passed."]
OBFUSCATED = ["Runs g r e a t.", "Runs gr​eat.", "Like  new condition.", "like new", "L1KE NEW", "lіke new", "NOTHING   WRONG with it."]


@pytest.mark.parametrize("txt", EUPHEMISMS, ids=[t[:40] for t in EUPHEMISMS])
def test_euphemisms_for_a_material_defect_are_caught(txt):
    assert lint(setf("body", txt)), f"slipped: {txt!r}"


@pytest.mark.parametrize("txt", OBFUSCATED, ids=["spaced", "zero-width", "double-space", "nbsp", "leet", "cyrillic-i", "multi-space"])
def test_obfuscated_overstatements_are_caught(txt):
    assert lint(setf("body", txt)), f"slipped: {txt!r}"


def test_a_material_defect_must_be_visible_in_the_headline_or_start_of_the_body():
    fluff = "Great deal on a classic mower. " * 120
    assert lint(setf("body", fluff[:3900])), "3900 chars of fluff with the defect only in the disclosures list"


@pytest.mark.parametrize("label", ["Ready to Work", "Quick Turn"])
def test_a_label_cannot_overstate_a_material_defect(label):
    assert lint(lambda v: (v.__setitem__("label", label), v.__setitem__("headline", "Ready to work riding mower"))), label


def test_downgrading_or_deleting_a_defect_in_the_inventory_does_not_unlock_untruthful_prose():
    assert lint(setf("body", "Runs great and mows fine."), lambda i: i["defects"][0].update(severity="minor")), "severity downgrade unlocked 'runs great'"


@pytest.mark.xfail(strict=True, reason="F-61: an inventory with the defect deleted lints clean against a view without it")
def test_a_defect_cannot_vanish_between_inventory_versions():
    assert lint(lambda v: v.__setitem__("disclosures", []), lambda i: i.__setitem__("defects", []))


@pytest.mark.xfail(strict=True, reason="F-62: a view can attach a provenance_id the inventory fact does not have (the check only runs when the inventory fact has one)")
def test_a_view_cannot_invent_provenance_for_a_fact():
    assert lint(lambda v: v["facts"][0].update(provenance_id=PROV))


def test_a_verification_claim_needs_a_verified_fact_about_that_claim():
    def inv_f(i):
        i["facts"][0].update(basis="verified", provenance_id=PROV)

    def view_f(v):
        v["facts"][1] = {"fact_id": "f1", "basis": "verified", "provenance_id": PROV}
        v["body"] = "Inspected and certified. Tested and working."

    assert lint(view_f, inv_f)


# ------------------------------------------------------------------ mission / ledger / plan
def mp(f):
    p = copy.deepcopy(PLAN)
    f(p)
    return mission.plan_errors(p)


@pytest.mark.parametrize("name,f", [
    ("overspend", lambda p: p["legs"][0].update(cash_at_risk=900)), ("do-not-spend-with-legs", lambda p: p.__setitem__("recommendation", "DO_NOT_SPEND")),
    ("gap-invented-for-null-target", lambda p: (p["mission"].update(weekly_target_usd=None), p.__setitem__("remaining_gap", 100))),
    ("gap-arithmetic", lambda p: p.__setitem__("remaining_gap", 1)), ("duplicate-item", lambda p: p["legs"][1].update(item_id=p["legs"][0]["item_id"])),
    ("leg-range-order", lambda p: p["legs"][0]["expected_net"].update(low=90)), ("week-range-order", lambda p: p["projected_week"].update(low=900)),
    ("avail-arithmetic", lambda p: p["ledger"].update(available_to_deploy=999)), ("impairment-over-principal", lambda p: p["ledger"].update(principal_impairment=900)),
    ("impairment-with-earned", lambda p: p["ledger"].update(principal_impairment=10, earned_working_capital=10)),
    ("negative-cash-leg", lambda p: p["legs"][0].update(cash_at_risk=-5)), ("probability-above-1", lambda p: p["legs"][0].update(success_probability=1.2))])
def test_mission_plan_invariants_that_hold(name, f):
    assert mp(f), f"{name} slipped"


@pytest.mark.parametrize("what,fn", [
    ("ledger-available-nan", lambda: mp(lambda p: p["ledger"].update(available_to_deploy=NAN))),
    ("ledger-deployed-nan", lambda: mp(lambda p: p["ledger"].update(capital_deployed=NAN))),
    ("leg-cash-nan", lambda: mp(lambda p: p["legs"][0].update(cash_at_risk=NAN))),
    ("ledger-inf", lambda: mp(lambda p: p["ledger"].update(available_to_deploy=INF, protected_principal=INF))),
    ("campaign-max-price-nan", lambda: campaign.errors({**CAMP, "criteria": {**CAMP["criteria"], "max_price_usd": NAN}})),
    ("autopilot-limits-nan", lambda: campaign.errors({**CAMP, "autonomy": {"level": "BOUNDED_AUTOPILOT", "limits": {"max_total_spend_usd": NAN, "max_offer_usd": NAN, "expires_at": "2099-01-01T00:00:00Z"}}})),
    ("valuation-range-nan", lambda: valuation.errors({**VAL, "ranges": {**VAL["ranges"], "likely_sale": {"low": NAN, "high": NAN}}})),
    ("valuation-range-inf", lambda: valuation.errors({**VAL, "ranges": {**VAL["ranges"], "likely_sale": {"low": 1, "high": INF}}}))])
def test_non_finite_numbers_are_rejected(what, fn):
    assert fn(), f"{what} accepted"


def test_the_projection_and_the_gap_are_derived_never_invented():
    assert mp(lambda p: (p["projected_week"].update(low=None, likely=None, high=None), p.__setitem__("remaining_gap", 0))), "null projection with gap 0"
    assert mp(lambda p: (p["projected_week"].update(low=9000, likely=9500, high=9999), p.__setitem__("remaining_gap", 1500 - 9500))), "9500 projected from legs worth 455"


@pytest.mark.parametrize("name,f", [
    ("deploy-no-legs", lambda p: (p.__setitem__("legs", []), p["projected_week"].update(low=0, likely=0, high=0), p.__setitem__("remaining_gap", 1500))),
    ("hold-with-spend", lambda p: p.__setitem__("recommendation", "HOLD")), ("unknown-with-spend", lambda p: p.__setitem__("recommendation", "UNKNOWN")),
    pytest.param("hours-exceeded", lambda p: p["mission"].update(hours_available=2), marks=residual("F-65 residual: legs needing more hours than available")), pytest.param("period-inverted", lambda p: p["mission"]["period"].update(start="2026-10-11", end="2026-10-05"), marks=residual("F-65 residual: inverted period")),
    pytest.param("duplicate-scorecard", lambda p: p["legs"][1].update(scorecard_id=p["legs"][0]["scorecard_id"]), marks=residual("F-65 residual: duplicate scorecard in two legs")), pytest.param("stale-ledger", lambda p: p["ledger"].update(as_of="2020-01-01T00:00:00Z"), marks=residual("F-65 residual: ancient ledger as_of")),
    pytest.param("deploy-with-impairment", lambda p: p["ledger"].update(principal_impairment=100, available_to_deploy=370), marks=residual("F-65 residual: DEPLOY while principal is impaired"))])
def test_a_plan_must_be_coherent(name, f):
    assert mp(f), f"{name} accepted"


# ------------------------------------------------------------------ campaign
def cp(f):
    c = copy.deepcopy(CAMP)
    f(c)
    return campaign.errors(c)


@pytest.mark.parametrize("name,f", [
    ("autopilot-without-limits", lambda c: c["autonomy"].update(level="BOUNDED_AUTOPILOT")),
    ("offer-above-max-price", lambda c: c["autonomy"].update(level="ASSISTED_DEAL", limits={"max_offer_usd": 99999})),
    ("offer-above-total-spend", lambda c: c["autonomy"].update(level="ASSISTED_DEAL", limits={"max_offer_usd": 500, "max_total_spend_usd": 100})),
    ("bad-level", lambda c: c["autonomy"].update(level="FULL_AUTO")), ("negative-price", lambda c: c["criteria"].update(max_price_usd=-1)),
    ("max-matches-string", lambda c: c["stop_conditions"].update(max_matches="3")), ("extra-key", lambda c: c.__setitem__("grant", "spend"))])
def test_campaign_rules_that_hold(name, f):
    assert cp(f), f"{name} slipped"


def test_only_watch_only_and_recommend_may_run_and_only_when_active():
    for level, status, want in [("WATCH_ONLY", "ACTIVE", True), ("RECOMMEND", "ACTIVE", True), ("ASSISTED_DEAL", "ACTIVE", False),
                                ("BOUNDED_AUTOPILOT", "ACTIVE", False), ("RECOMMEND", "PAUSED", False), ("RECOMMEND", "EXPIRED", False),
                                ("RECOMMEND", "CANCELLED", False), ("RECOMMEND", "FULFILLED", False)]:
        c = copy.deepcopy(CAMP)
        c["autonomy"]["level"], c["status"] = level, status
        assert campaign.may_run(c) is want, (level, status)


def test_an_expired_or_invalid_campaign_does_not_run():
    c = copy.deepcopy(CAMP)
    c["autonomy"]["level"], c["status"] = "RECOMMEND", "ACTIVE"
    c["stop_conditions"]["expires_at"] = "2020-01-01T00:00:00Z"
    assert campaign.may_run(c) is False, "expired stop condition still runs"
    assert campaign.may_run({}) is False


@pytest.mark.xfail(strict=True, reason="F-66: an autopilot whose own limits.expires_at is already in the past validates")
def test_autopilot_limits_must_not_be_expired_at_creation():
    assert cp(lambda c: c["autonomy"].update(level="BOUNDED_AUTOPILOT", limits={"max_total_spend_usd": 300, "max_offer_usd": 200, "expires_at": "2000-01-01T00:00:00Z"}))


# ------------------------------------------------------------------ valuation
def vp(f):
    v = copy.deepcopy(VAL)
    f(v)
    return valuation.errors(v)


@pytest.mark.parametrize("name,f", [
    ("disclaimer-false", lambda v: v.__setitem__("not_an_appraisal", False)), ("disclaimer-missing", lambda v: v.pop("not_an_appraisal")),
    ("range-without-evidence", lambda v: v.__setitem__("evidence", [])), ("low-above-high", lambda v: v["ranges"]["likely_sale"].update(low=900, high=100)),
    ("no-ranges-medium", lambda v: (v.__setitem__("ranges", {k: None for k in v["ranges"]}), v.__setitem__("confidence", "medium"), v.__setitem__("reason_unknown", "x"))),
    ("no-ranges-no-reason", lambda v: (v.__setitem__("ranges", {k: None for k in v["ranges"]}), v.__setitem__("confidence", "UNKNOWN"))),
    ("high-on-asking-only", lambda v: (v.__setitem__("confidence", "high"), v.__setitem__("evidence", [{"kind": "asking_comp", "ref": "x"}]))),
    ("extra-appraised-key", lambda v: v.__setitem__("appraised_value", 5000)), ("negative-low", lambda v: v["ranges"]["likely_sale"].update(low=-5))])
def test_valuation_rules_that_hold(name, f):
    assert vp(f), f"{name} slipped"


def test_a_home_may_return_all_unknown_with_a_reason():
    assert valuation.errors(load("valuation--home-unknown.example.json")) == []


@pytest.mark.parametrize("name,f", [
    ("fast-sale-above-suggested-list", lambda v: v["ranges"].update(fast_sale={"low": 9000, "high": 9500})),
    pytest.param("as-is-above-after-repair", lambda v: v["ranges"].update(as_is={"low": 9000, "high": 9500}), marks=residual("F-67 residual: as_is above after-repair values")),
    ("zero-width-fake-precision", lambda v: v["ranges"]["likely_sale"].update(low=1234, high=1234)),
    ("useless-width", lambda v: v["ranges"]["likely_sale"].update(low=1, high=1000000)),
    ("high-on-one-bare-sold-comp", lambda v: (v.__setitem__("confidence", "high"), v.__setitem__("evidence", [{"kind": "sold_comp", "ref": "x"}]))),
    pytest.param("medium-on-priors-only", lambda v: (v.__setitem__("confidence", "medium"), v.__setitem__("evidence", [{"kind": "prior", "ref": "p"}])), marks=residual("F-67 residual: medium confidence on priors only")),
    ("home-high-on-one-record", lambda v: (v["subject"].update(kind="home"), v.__setitem__("confidence", "high"), v.__setitem__("evidence", [{"kind": "record", "ref": "county"}])))])
def test_a_valuation_is_internally_consistent_and_confidence_is_earned(name, f):
    assert vp(f), f"{name} accepted"


@pytest.mark.parametrize("name,f", [
    ("description-appraised", lambda v: v["subject"].update(description="Certified appraised value $5,000")),
    pytest.param("note-guaranteed", lambda v: v["evidence"][0].update(note="verified and guaranteed by appraiser"), marks=residual("F-68 residual: 'verified and guaranteed by appraiser' in an evidence note")),
    pytest.param("null-range-not-in-unknowns", lambda v: (v["ranges"].update(as_is=None), v.__setitem__("unknowns", [])), marks=residual("F-68 residual: null range not reconciled with `unknowns`"))])
def test_a_valuation_never_claims_to_be_an_appraisal_and_lists_its_unknowns(name, f):
    assert vp(f), f"{name} accepted"
