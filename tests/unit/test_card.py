"""Deal Sniffer opportunity card (ADR-0011): honest, deterministic, contract-valid, decision-ready."""

import copy

import pytest
import sqlalchemy as sa

from mbos import card as cardmod
from mbos.contracts import schemas
from mbos.ledger import load_receipts
from tests.helpers.seed import seed_flow

PROV = "prov_01JA0000000000000000000001"


def _inputs(engine, item_id):
    with engine.connect() as c:
        item = c.execute(sa.text("SELECT body FROM mbos.items WHERE item_id = :i"), {"i": item_id}).scalar_one()
        receipts = load_receipts(c, "item_id = :i", {"i": item_id})
        areqs = [r[0] for r in c.execute(sa.text("SELECT body FROM mbos.action_requests WHERE item_id = :i ORDER BY body->>'created_at'"), {"i": item_id})]
    return item, receipts, areqs


def test_card_without_enrichment_is_valid_and_never_fabricates(ledger_db):
    ids = seed_flow(ledger_db, act=False)
    item, receipts, areqs = _inputs(ledger_db, ids["item_id"])
    c = cardmod.build_card(item, receipts, areqs)
    assert cardmod.validate_card(c) == [], cardmod.validate_card(c)
    # seller data, dates, seasonality, value-add plan: nothing was supplied, so everything is UNKNOWN and listed
    for path in ("listing_activity.posted_at", "listing_activity.updated_at", "listing_activity.stale_risk",
                 "seller.account_age", "seller.rating", "seller.complaint_signals", "seasonality.demand_now",
                 "value_add_plan.plan", "economics.recommended_opening_offer", "logistics.transport_mode"):
        assert path in c["unknowns"], path
    assert c["seller"]["confidence"] == "UNKNOWN" and c["listing_activity"]["recent_activity"] == []
    assert c["logistics"]["trailer_owned"]["value"] is False and c["logistics"]["borrowed_trailer_possible"]["value"] is True
    assert c["logistics"]["borrowed_trailer_confirmed"]["value"] == "UNKNOWN"  # never assumed


def test_card_uses_stored_economics_with_basis_and_provenance(ledger_db):
    ids = seed_flow(ledger_db, act=False)
    item, receipts, areqs = _inputs(ledger_db, ids["item_id"])
    e = cardmod.build_card(item, receipts, areqs)["economics"]
    assert e["asking_price"]["basis"] == "FACT" and e["asking_price"]["value"] == 950
    assert e["resale_conservative"]["value"] == 1800 and e["resale_likely"]["value"] == 2100 and e["resale_optimistic"]["value"] == 2400
    assert e["expected_net_profit"]["basis"] == "INFERENCE" and e["expected_net_profit"]["provenance_id"].startswith("prov_")
    assert e["expected_repair_material_cost"]["value"] == 300


def test_card_hash_is_deterministic_and_content_sensitive(ledger_db):
    ids = seed_flow(ledger_db, act=False)
    item, receipts, areqs = _inputs(ledger_db, ids["item_id"])
    a, b = cardmod.build_card(item, receipts, areqs), cardmod.build_card(item, list(reversed(receipts)), areqs)
    assert a["card_hash"] == b["card_hash"]  # receipt order irrelevant
    changed = copy.deepcopy(item)
    changed["normalized"]["price"]["amount"] = 800
    assert cardmod.build_card(changed, receipts, areqs)["card_hash"] != a["card_hash"]


def test_timeline_and_activity_trail_come_from_receipts(ledger_db):
    ids = seed_flow(ledger_db)  # YES + dry-run comms executed + outcome
    item, receipts, areqs = _inputs(ledger_db, ids["item_id"])
    c = cardmod.build_card(item, receipts, areqs)
    stages = [t["stage"] for t in c["status"]["timeline"]]
    for s in ("DISCOVERED", "RESEARCHED", "SCORED", "CONTACT APPROVED", "CONTACT SENT"):
        assert s in stages, stages
    assert "NEGOTIATING" not in stages and "QUALIFIED" not in stages  # no event source yet: never invented
    assert len(c["activity_trail"]) == len(receipts) and all(t["inputs"] for t in c["activity_trail"])
    assert c["activity_trail"][-1]["next_action"] != "(done)"
    sent = next(t for t in c["activity_trail"] if t["what"].startswith("executed"))
    assert "dry-run" in sent["result"] and sent["receipt_id"].startswith("rcpt_")


def test_recommendation_vocabulary_and_waiting(ledger_db):
    ids = seed_flow(ledger_db, act=False)
    item, receipts, areqs = _inputs(ledger_db, ids["item_id"])
    r = cardmod.build_card(item, receipts, areqs)["recommendation"]
    assert r["action"] == "CONTACT" and r["waiting"] is False and r["requires_step_up"] is True
    ids2 = seed_flow(ledger_db, "FIX-LEAD-SMARTHOME-1", outcome=False)
    item2, receipts2, areqs2 = _inputs(ledger_db, ids2["item_id"])
    r2 = cardmod.build_card(item2, receipts2, areqs2)["recommendation"]
    # F-31: the only executed contact is a DRY-RUN, so there is no seller to wait for
    assert r2["action"] == "CONTACT" and r2["waiting"] is False and "dry-run" in r2["why"].lower()


def test_pass_and_pass_on_priors_are_not_discarded():
    base = {"item_id": "itm_01JA0000000000000000000001", "state": "ARCHIVED", "type": "flip", "category": "mower",
            "normalized": {"title": "x"}, "sources": [{"source": "s", "url": "u", "provenance_id": PROV}],
            "recommendation": {"verdict": "PASS", "rationale": ["EV negative"]}, "scores": {"scorecard": {}}}
    assert cardmod._recommend(base, [], "PASSED")["action"] == "PASS"
    base["scores"]["scorecard"] = {"pass_on_priors": True}
    out = cardmod._recommend(base, [], "PASSED")
    assert out["action"] == "HOLD" and "assumptions" in out["why"]


def test_enrichment_is_taken_verbatim_and_validated(ledger_db):
    ids = seed_flow(ledger_db, act=False)
    item, receipts, areqs = _inputs(ledger_db, ids["item_id"])
    enr = {"listing_activity": {"posted_at": {"value": "2026-05-07T00:00:00Z", "basis": "FACT", "provenance_id": PROV},
                                "updated_at": {"value": "2026-09-29T00:00:00Z", "basis": "FACT", "provenance_id": PROV},
                                "stale_risk": {"value": "medium", "basis": "INFERENCE"},
                                "recent_activity": ["Seller edited the listing 8 days ago"]},
           "seller": {"rating": {"value": 4.8, "basis": "FACT", "provenance_id": PROV}, "confidence": "medium"},
           "logistics": {"transport_mode": {"value": "fits_truck", "basis": "INFERENCE"}},
           "seasonality": {"demand_now": {"value": "normal", "basis": "INFERENCE"}, "peak_months": [4, 5]},
           "value_add": {"plan": {"value": "Replace the cracked fuel pump housing (common on this model); photograph and relist.", "basis": "RECOMMENDATION"},
                         "model_specific_risks": [{"risk": "OEM ignition module is backordered 6+ weeks", "kind": "parts_availability",
                                                   "basis": "FACT", "source": "OEM parts catalog 2026-09-01"}]},
           "why": ["Old listing, but the seller updated it 8 days ago, which lowers stale-listing risk."],
           "_prov": {"why": PROV}}  # lane reasons are shown only with provenance (F-29)
    c = cardmod.build_card(item, receipts, areqs, enr)
    assert cardmod.validate_card(c) == []
    assert c["listing_activity"]["stale_risk"]["value"] == "medium" and c["seller"]["rating"]["value"] == 4.8
    assert c["logistics"]["transport_mode"]["value"] == "fits_truck" and c["logistics"]["trailer_needed"]["value"] is False
    assert c["why"][0].startswith("Old listing") and "seller.rating" not in c["unknowns"]
    assert "listing_activity.posted_at" not in c["unknowns"] and "seller.account_age" in c["unknowns"]


def test_malformed_enrichment_degrades_to_unknown_not_to_a_guess(ledger_db):
    ids = seed_flow(ledger_db, act=False)
    item, receipts, areqs = _inputs(ledger_db, ids["item_id"])
    enr = {"seller": {"rating": {"value": 5, "basis": "MADE-UP"}, "account_age": "3 years"},  # bad basis / bare string
           "listing_activity": {"posted_at": {"value": "2026-05-07T00:00:00Z"}}}               # no basis
    c = cardmod.build_card(item, receipts, areqs, enr)
    assert c["seller"]["rating"]["value"] == "UNKNOWN" and c["seller"]["account_age"]["value"] == "UNKNOWN"
    assert c["listing_activity"]["posted_at"]["value"] == "UNKNOWN"
    assert cardmod.validate_card(c) == []


@pytest.mark.parametrize("text", ["Check compression and spark first.", "Inspect the fuel system.", "Check the oil level",
                                  "Verify it starts and runs.", "Look for leaks"])
def test_elementary_mechanical_advice_is_rejected(ledger_db, text):
    ids = seed_flow(ledger_db, act=False)
    item, receipts, areqs = _inputs(ledger_db, ids["item_id"])
    c = cardmod.build_card(item, receipts, areqs, {"value_add": {"plan": {"value": text, "basis": "RECOMMENDATION"}}})
    assert any("elementary advice" in e for e in cardmod.validate_card(c))


def test_model_specific_risk_needs_a_source(ledger_db):
    ids = seed_flow(ledger_db, act=False)
    item, receipts, areqs = _inputs(ledger_db, ids["item_id"])
    c = cardmod.build_card(item, receipts, areqs, {"value_add": {"model_specific_risks": [
        {"risk": "Known head-gasket weakness on this engine", "basis": "INFERENCE"}]}})
    assert c["value_add_plan"]["model_specific_risks"] == []        # not shown at all: UNKNOWN beats an unsourced claim
    assert cardmod.validate_card(c) == []


def test_contract_is_additive_and_frozen_files_untouched():
    from tests.helpers.common import ROOT
    import subprocess
    out = subprocess.run(["git", "diff", "--stat", "origin/research/agent-01-coordinator~0", "--", "docs/research/contracts/item.schema.json",
                          "docs/research/contracts/receipt.schema.json", "docs/research/contracts/action-request.schema.json"],
                         cwd=ROOT, capture_output=True, text=True).stdout
    assert out.strip() == ""  # card.schema.json is a NEW file; no frozen v1.0.0 schema changed


def test_enrichment_persists_through_the_ledger_and_renders(ledger_db):
    """Interim convention: block -> artifact + Item.research[] citation + provenance + receipt, no contract change."""
    from mbos import ledger, spine
    ids = seed_flow(ledger_db, act=False)
    block = {"stale_risk": {"value": "low", "basis": "INFERENCE"},
             "recent_activity": ["Seller edited the listing 3 days ago"]}
    with ledger_db.begin() as c:
        prov = ledger.tool_provenance(c, "agent-02-opportunity.listing_activity")
        spine.record_enrichment(c, ids["item_id"], "listing_activity", block, prov, summary="listing activity", agent="agent-02-opportunity")
        with pytest.raises(ValueError):
            spine.record_enrichment(c, ids["item_id"], "not_a_block", {}, prov)
    with ledger_db.connect() as c:
        item, receipts, areqs = cardmod.load_inputs(c, ids["item_id"])
        enr = cardmod.enrichment_from_item(c, item)
    assert enr["listing_activity"] == block and schemas.errors("item", item) == []
    card = cardmod.build_card(item, receipts, areqs, enr)
    assert card["listing_activity"]["stale_risk"]["value"] == "low" and cardmod.validate_card(card) == []
    assert any("card enrichment listing_activity" in t["why"] for t in card["activity_trail"])  # visible in the trail


def test_text_card_is_decision_ready_and_honest(ledger_db):
    ids = seed_flow(ledger_db, outcome=False)
    item, receipts, areqs = _inputs(ledger_db, ids["item_id"])
    text = cardmod.render_text(cardmod.build_card(item, receipts, areqs))
    for must in ("6X12 ENCLOSED TRAILER", "STALE RISK: UNKNOWN", "RECOMMENDATION: CONTACT", "TRANSPORT:", "ACTIVITY (every action has a receipt)",
                 "SELLER: UNKNOWN", "rcpt_", "Contact Sent"):
        assert must in text, must
    assert "check compression" not in text.lower()


def test_closed_item_recommends_no_further_action(ledger_db):
    from mbos import spine
    ids = seed_flow(ledger_db, outcome=False)
    with ledger_db.begin() as c:
        spine.record_outcome(c, ids["item_id"], "flip_sold", realized={"revenue": 2100, "total_cost": 1300})
    item, receipts, areqs = _inputs(ledger_db, ids["item_id"])
    c = cardmod.build_card(item, receipts, areqs)
    assert c["status"]["current"] == "CLOSED" and c["recommendation"]["action"] == "PASS"
    assert "requires_step_up" not in c["recommendation"] and "Closed" in c["recommendation"]["why"]


def test_machine_noise_never_reaches_michaels_reasons(ledger_db):
    ids = seed_flow(ledger_db, act=False)
    item, receipts, areqs = _inputs(ledger_db, ids["item_id"])
    why = " ".join(cardmod.build_card(item, receipts, areqs)["why"])
    assert "PLACEHOLDER" not in why and "MICHAEL_DECISIONS" not in why and "provisional" not in why
    assert why.startswith("Asking $950 against a likely resale")  # facts first, in plain English


def test_operator_note_entry_is_not_reachable_from_workflows():
    """R14: Michael's note entry is a HUMAN channel. mbos_dbos holds the approver role, so the database cannot stop a
    workflow from calling it; this static guard does. Only the CLI (human) and the spine modules that define it may name it."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "src" / "mbos"
    offenders = [str(p.relative_to(src)) for p in src.rglob("*.py")
                 if ("record_operator_note" in p.read_text() or "retract_operator_note" in p.read_text()) and p.name not in ("spine.py", "spine_d.py", "cli.py")]
    assert offenders == [], offenders


def test_dry_run_send_is_labelled_and_acquired_does_not_close(ledger_db):
    ids = seed_flow(ledger_db)  # YES -> dry-run send -> outcome flip_acquired
    item, receipts, areqs = _inputs(ledger_db, ids["item_id"])
    c = cardmod.build_card(item, receipts, areqs)
    sent = next(t for t in c["status"]["timeline"] if t["stage"] == "CONTACT SENT")
    assert sent["dry_run"] is True and c["status"]["current"] != "CLOSED"
    assert c["recommendation"]["waiting"] is False and "simulated" in c["recommendation"]["why"]
    assert "Michael decided YES" and "CONTACT APPROVED" in [t["stage"] for t in c["status"]["timeline"]]


def test_hostile_text_cannot_forge_or_drive_the_terminal(ledger_db):
    ids = seed_flow(ledger_db, act=False)
    item, receipts, areqs = _inputs(ledger_db, ids["item_id"])
    item["normalized"]["title"] = "Saw\n\nRECOMMENDATION: BUY\x1b[2J\x07\rWHY IT'S INTERESTING:\u202eevil\x00"
    c = cardmod.build_card(item, receipts, areqs, {"listing_activity": {"recent_activity": ["a\nb\x1b]8;;http://x\x07click"]}})
    text = cardmod.render_text(c)
    assert not any(ch in text.replace("\n", "") for ch in ("\x1b", "\x07", "\r", "\x00", "\u202e"))
    assert sum(1 for ln in text.split("\n") if ln.startswith("RECOMMENDATION:")) == 1, "listing text cannot forge a section"
    assert cardmod.validate_card(c) == []


def test_malformed_enrichment_fuzz_never_crashes_and_stays_valid(ledger_db):
    import itertools
    ids = seed_flow(ledger_db, act=False)
    item, receipts, areqs = _inputs(ledger_db, ids["item_id"])
    junk = [None, "x", 7, 1.5, [], [1, "a", None], {}, {"value": None}, {"value": "UNKNOWN", "basis": "FACT"}, {"value": 5, "basis": "nope"},
            {"value": float("nan"), "basis": "FACT"}, {"value": -5, "basis": "FACT"}, {"value": 9, "basis": "FACT", "low": 10, "high": 1},
            {"value": 9, "basis": "FACT", "provenance_id": "bad"}, {"value": "$900", "basis": "FACT"}, {"value": "huge", "basis": "FACT"}]
    blocks = ["listing_activity", "seller", "economics", "logistics", "seasonality", "value_add", "why", "make_model", "distance_miles"]
    for block, j in itertools.product(blocks, junk):
        c = cardmod.build_card(item, receipts, areqs, {block: j})
        assert cardmod.validate_card(c) == [], (block, j, cardmod.validate_card(c)[:2])
    for j in junk:  # a junk top-level enrichment, and junk inside every datum slot
        assert cardmod.validate_card(cardmod.build_card(item, receipts, areqs, j)) == []
        for slot in ("stale_risk", "posted_at", "rating", "demand_now", "transport_mode", "difficulty", "resale_likely", "fuel_cost"):
            for b in ("listing_activity", "seller", "seasonality", "logistics", "economics"):
                cardmod.build_card(item, receipts, areqs, {b: {slot: j, "peak_months": j, "recent_activity": j, "confidence": j}})


def test_lane_values_are_validated_not_just_shaped(ledger_db):
    ids = seed_flow(ledger_db, act=False)
    item, receipts, areqs = _inputs(ledger_db, ids["item_id"])
    d = lambda v: {"value": v, "basis": "INFERENCE"}
    c = cardmod.build_card(item, receipts, areqs, {"listing_activity": {"stale_risk": d("catastrophic"), "age_days": d(-4)},
                                                    "seasonality": {"demand_now": d("maybe"), "peak_months": [0, 13]},
                                                    "logistics": {"transport_mode": d("teleport"), "difficulty": d("impossible")},
                                                    "economics": {"resale_likely": d("a lot")}})
    assert c["listing_activity"]["stale_risk"]["value"] == "UNKNOWN" and c["listing_activity"]["age_days"]["value"] == "UNKNOWN"
    assert c["seasonality"]["demand_now"]["value"] == "UNKNOWN" and "peak_months" not in c["seasonality"]
    assert c["logistics"]["transport_mode"]["value"] == "UNKNOWN" and c["economics"]["resale_likely"]["value"] != "a lot"


def test_lane_reasons_without_provenance_are_not_shown(ledger_db):
    ids = seed_flow(ledger_db, act=False)
    item, receipts, areqs = _inputs(ledger_db, ids["item_id"])
    c = cardmod.build_card(item, receipts, areqs, {"why": ["Trust me, it's great."]})
    assert not any("Trust me" in w for w in c["why"]) and "why_provenance" not in c


def test_card_hash_is_order_independent_and_verified(ledger_db):
    import random
    ids = seed_flow(ledger_db)
    item, receipts, areqs = _inputs(ledger_db, ids["item_id"])
    base = cardmod.build_card(item, receipts, areqs)["card_hash"]
    rnd = random.Random(7)
    for _ in range(30):
        r, a = receipts[:], areqs[:]
        rnd.shuffle(r); rnd.shuffle(a)
        assert cardmod.build_card(item, r, a)["card_hash"] == base
    card = cardmod.build_card(item, receipts, areqs)
    card["economics"]["asking_price"]["value"] = 1  # tampered after the fact
    assert any("card_hash" in e for e in cardmod.validate_card(card))


def test_other_items_receipts_do_not_leak_into_the_trail(ledger_db):
    a, b = seed_flow(ledger_db, act=False), seed_flow(ledger_db, "FIX-LEAD-SMARTHOME-1", act=False)
    item, receipts, areqs = _inputs(ledger_db, a["item_id"])
    with ledger_db.connect() as c:
        from mbos.ledger import load_receipts
        everything = load_receipts(c)
    card = cardmod.build_card(item, everything, areqs)  # caller passed EVERY receipt in the ledger
    assert len(card["activity_trail"]) == len(receipts)


@pytest.mark.parametrize("text", ["Test compression", "Do a compression test", "See if it starts", "Try starting it",
                                  "Check that it starts and runs", "Confirm it runs", "Make sure the engine turns over",
                                  "Inspect for oil leaks", "Verify spark at the plug", "Pull the plug and look at it"])
def test_lint_catches_more_phrasings(ledger_db, text):
    assert cardmod.elementary_advice(text), text


@pytest.mark.parametrize("src", ["n/a", "none", "x", "trust me", "", "UNKNOWN", "?", "google"])
def test_junk_sources_do_not_launder_a_risk(ledger_db, src):
    ids = seed_flow(ledger_db, act=False)
    item, receipts, areqs = _inputs(ledger_db, ids["item_id"])
    c = cardmod.build_card(item, receipts, areqs, {"value_add": {"model_specific_risks": [
        {"risk": "Known head-gasket weakness on this engine", "basis": "INFERENCE", "source": src}]}})
    assert c["value_add_plan"]["model_specific_risks"] == [], src    # a junk source cannot launder a claim
    assert cardmod.validate_card(c) == []


def test_listing_flags_are_visible_on_the_card(ledger_db):
    ids = seed_flow(ledger_db, act=False)
    item, receipts, areqs = _inputs(ledger_db, ids["item_id"])
    item["normalized"]["flags"] = ["injection_suspected", "needs_review"]
    c = cardmod.build_card(item, receipts, areqs)
    assert "injection_suspected" in c["item"]["flags"] and "injection_suspected" in cardmod.render_text(c)
    assert cardmod.validate_card(c) == []


@pytest.mark.parametrize("text", ["Look for any damage", "Check the carburetor", "Check the fluids", "Check carburetors for varnish"])
def test_lint_catches_the_remaining_phrasings(text):
    assert cardmod.elementary_advice(text), text


@pytest.mark.parametrize("bad", ["not a date", "2999-01-01T00:00:00Z", "", 12345, None])
def test_listing_dates_must_be_real_and_not_from_the_future(ledger_db, bad):
    ids = seed_flow(ledger_db, act=False)
    item, receipts, areqs = _inputs(ledger_db, ids["item_id"])
    c = cardmod.build_card(item, receipts, areqs, {"listing_activity": {"posted_at": {"value": bad, "basis": "FACT"}}})
    assert c["listing_activity"]["posted_at"]["value"] == "UNKNOWN" and cardmod.validate_card(c) == []


def test_an_edit_cannot_precede_the_post(ledger_db):
    ids = seed_flow(ledger_db, act=False)
    item, receipts, areqs = _inputs(ledger_db, ids["item_id"])
    la = {"posted_at": {"value": "2026-09-01T00:00:00Z", "basis": "FACT"}, "updated_at": {"value": "2026-08-01T00:00:00Z", "basis": "FACT"}}
    c = cardmod.build_card(item, receipts, areqs, {"listing_activity": la})
    assert c["listing_activity"]["posted_at"]["value"] != "UNKNOWN" and c["listing_activity"]["updated_at"]["value"] == "UNKNOWN"


def test_dry_run_headline_is_marked(ledger_db):
    ids = seed_flow(ledger_db, outcome=False)  # YES -> dry-run send
    item, receipts, areqs = _inputs(ledger_db, ids["item_id"])
    text = cardmod.render_text(cardmod.build_card(item, receipts, areqs))
    assert "DRY-RUN: simulated, nothing sent" in text and "Contact Sent (dry-run)" in text


def test_bare_number_dates_are_not_facts(ledger_db):
    ids = seed_flow(ledger_db, act=False)
    item, receipts, areqs = _inputs(ledger_db, ids["item_id"])
    c = cardmod.build_card(item, receipts, areqs, {"listing_activity": {"posted_at": {"value": 20261005, "basis": "FACT"}}})
    assert c["listing_activity"]["posted_at"]["value"] == "UNKNOWN"


def test_a_dropped_risk_leaves_a_trace(ledger_db, caplog):
    import logging
    ids = seed_flow(ledger_db, act=False)
    item, receipts, areqs = _inputs(ledger_db, ids["item_id"])
    with caplog.at_level(logging.WARNING, logger="mbos.card"):
        c = cardmod.build_card(item, receipts, areqs, {"value_add": {"model_specific_risks": [
            {"risk": "Known head-gasket weakness on this engine", "basis": "INFERENCE", "source": "n/a"}]}})
    assert c["value_add_plan"]["model_specific_risks"] == []
    assert any("rejected" in u for u in c["unknowns"]) and "dropped 1 model-specific risk" in caplog.text


# ---- Michael's training examples (ARIA-20261007-1840): capital velocity, not a universal profit floor ----
def _base(ledger_db):
    ids = seed_flow(ledger_db, act=False)
    return _inputs(ledger_db, ids["item_id"])


def _scenario(base, *, cash, net, days, p_ok=0.9, scope=True, salvage=0, dom=3, sale_prob=0.95, comp_low=None, comp_high=None, profile=None):
    item, receipts, areqs = copy.deepcopy(base)
    d = item["scores"]["scorecard"].setdefault("derived", {})
    d.update(cash_tied_up=cash, ev_net_profit=net, time_to_cash_days=days, skill_fit=0.9, cost_out=cash, net_profit_deterministic=net)
    e = item["economics"]
    e["rehab"].update(repair_success_prob=p_ok, repair_scope_known=scope)
    e["downside"]["salvage_if_repair_fails"] = salvage
    e["resale"].update(sale_prob=sale_prob, expected_dom_days=dom)
    if comp_low is not None:
        e["resale"].update(comp_price_low=comp_low, comp_price_high=comp_high)
    return cardmod.build_card(item, receipts, areqs, profile=profile)


def test_micro_flip_tv_is_a_great_use_of_cash_despite_tiny_absolute_profit(ledger_db):
    c = _scenario(_base(ledger_db), cash=30, net=45, days=0.1, p_ok=0.8, salvage=15, comp_low=60, comp_high=100)  # 65-inch TV at ~$30
    e = c["economics"]
    assert e["opportunity_class"]["value"] == "MICRO_FLIP" and e["cash_multiple"]["value"] == 2.5
    assert e["capital_velocity"]["value"] > 10                                  # 150% return on cash in 0.1 day
    assert e["catastrophic_downside_probability"]["value"] == 0.2 and e["parts_out_floor"]["value"] == 15
    assert e["expected_gross_profit"]["low"] == 30 and e["expected_gross_profit"]["high"] == 70
    assert any("micro flip" in w for w in c["why"]) and cardmod.validate_card(c) == []


def test_old_mower_late_season_is_capital_intensive_despite_a_big_spread(ledger_db):
    c = _scenario(_base(ledger_db), cash=900, net=700, days=150, p_ok=0.9, dom=120, sale_prob=0.6)
    e = c["economics"]
    assert e["opportunity_class"]["value"] == "CAPITAL_INTENSIVE_FLIP"
    assert e["capital_velocity"]["value"] < 0.01                                # cash trapped for months
    assert any("capital-intensive" in w for w in c["why"])


def test_non_running_recon_is_a_different_class_from_the_tv(ledger_db):
    base = _base(ledger_db)
    tv = _scenario(base, cash=30, net=45, days=0.1)["economics"]["opportunity_class"]["value"]
    recon = _scenario(base, cash=300, net=500, days=14, p_ok=0.75, scope=False, salvage=120)
    assert tv != recon["economics"]["opportunity_class"]["value"] == "STANDARD_FLIP"
    assert recon["economics"]["repair_uncertainty"]["value"] == "high"          # engine/transmission fundamentals not yet confirmed


def test_no_universal_profit_floor_a_30_dollar_profit_item_is_not_rejected_by_the_card(ledger_db):
    c = _scenario(_base(ledger_db), cash=30, net=30, days=0.05)
    assert c["recommendation"]["action"] in ("CONTACT", "OFFER", "BUY", "COUNTER", "HOLD")  # derived from the machine verdict, never from a $ floor
    assert c["economics"]["capital_velocity"]["value"] > 10


def test_unknown_cash_context_is_said_not_assumed(ledger_db):
    base = _base(ledger_db)
    c = _scenario(base, cash=30, net=45, days=0.1)
    assert c["economics"]["current_cash_context"]["value"] == "UNKNOWN" and "economics.current_cash_context" in c["unknowns"]
    profile = cardmod.load_profile()
    profile["current_cash_context"] = {"value": "tight: about $400 available this week"}
    c2 = _scenario(base, cash=30, net=45, days=0.1, profile=profile)
    assert c2["economics"]["current_cash_context"]["basis"] == "FACT"


def test_velocity_fields_are_unknown_not_invented_without_numbers(ledger_db):
    ids = seed_flow(ledger_db, act=False)
    item, receipts, areqs = _inputs(ledger_db, ids["item_id"])
    item["scores"] = None
    item.pop("scores")
    c = cardmod.build_card(item, receipts, areqs)
    for k in ("cash_multiple", "capital_velocity", "opportunity_class"):
        assert c["economics"][k]["value"] == "UNKNOWN", k
    assert cardmod.validate_card(c) == []


def test_category_tags_need_evidence_provenance_and_known_tag(ledger_db):
    ids = seed_flow(ledger_db, act=False)
    item, receipts, areqs = _inputs(ledger_db, ids["item_id"])
    blk = {"tags": [
        {"tag": "mechanic_special", "evidence": [{"field": "description", "quote": "won't start, needs carb work"}]},
        {"tag": "parts_donor", "evidence": []},                                   # no evidence -> dropped
        {"tag": "quick_turn", "evidence": [{"field": "price", "quote": ""}]},     # empty quote -> dropped
        {"tag": "best_deal_ever", "evidence": [{"field": "t", "quote": "x"}]},   # unknown tag -> dropped
        {"tag": "mechanic_special", "evidence": [{"field": "t", "quote": "dup"}]},  # duplicate -> dropped
    ]}
    c = cardmod.build_card(item, receipts, areqs, {"category_tags": blk, "_prov": {"category_tags": PROV}})
    assert cardmod.validate_card(c) == []
    assert [t["tag"] for t in c["category_tags"]] == ["mechanic_special"]
    assert c["category_tags"][0]["basis"] == "INFERENCE" and c["category_tags"][0]["provenance_id"] == PROV
    assert "TAGS (inferred" in cardmod.render_text(c)
    # no provenance -> nothing shown, and absence is recorded as UNKNOWN rather than a "no"
    c2 = cardmod.build_card(item, receipts, areqs, {"category_tags": blk})
    assert c2["category_tags"] == [] and any(u.startswith("category_tags") for u in c2["unknowns"])


def test_category_tags_cleaned_of_injection_markup(ledger_db):
    ids = seed_flow(ledger_db, act=False)
    item, receipts, areqs = _inputs(ledger_db, ids["item_id"])
    q = "mechanic special \x1b[31m<script>alert(1)</script>"
    c = cardmod.build_card(item, receipts, areqs, {"category_tags": [{"tag": "mechanic_special", "evidence": [{"field": "d", "quote": q}]}],
                                                    "_prov": {"category_tags": PROV}})
    assert cardmod.validate_card(c) == []
    assert "\x1b" not in c["category_tags"][0]["evidence"][0]["quote"]


def test_service_item_is_a_service_job_not_a_flip_class(ledger_db):
    ids = seed_flow(ledger_db, act=False)
    item, receipts, areqs = _inputs(ledger_db, ids["item_id"])
    item = dict(item, type="service")
    c = cardmod.build_card(item, receipts, areqs)
    assert c["economics"]["opportunity_class"]["value"] == "SERVICE_JOB"
    assert c["economics"]["cash_multiple"]["value"] == "UNKNOWN"
    assert cardmod.validate_card(c) == []
