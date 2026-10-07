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
    assert r2["action"] == "CONTACT" and r2["waiting"] is True and "waiting" in r2["why"].lower()


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
                                                   "basis": "FACT", "source": "parts catalog"}]},
           "why": ["Old listing, but the seller updated it 8 days ago, which lowers stale-listing risk."]}
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
    assert any("without source" in e for e in cardmod.validate_card(c))


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
    ids = seed_flow(ledger_db)  # outcome recorded
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
