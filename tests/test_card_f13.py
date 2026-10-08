"""F-13: Michael's opportunity card at /item/<id>, built only from mbos.card (Agent 01's API), real spine."""

from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

from mbos import card as mc
from mbos import spine
from mbos.ledger import tool_provenance
from tests.conftest import PIN
from tests.test_operator_ui import approvals, effector_calls, open_request, post, q, ready, req, wait_state

HOSTILE = "<script>alert(1)</script> \"'><img src=x onerror=alert(2)> {{disclosure}}"


def item_page(ui, item_id, **kw):
    return req(ui, "GET", f"/item/{item_id}", **kw)


def test_zero_enrichment_card_is_honest_and_complete(rt, discover, ui):
    item_id, areq = ready(rt, discover)
    s, _, body = item_page(ui, item_id)
    assert s == 200
    for h in ("Listing activity", "Seller", "Why it is interesting", "Estimated numbers", "Value-add plan", "Seasonality",
              "Transport", "System status", "Recommendation", "Your decision", "Activity trail (every action has a receipt)",
              "UNKNOWN ("):
        assert h in body, h
    assert "Seller style: UNKNOWN" in body and "<b class='unk'>UNKNOWN</b>" in body
    res = ui.store.opportunity_card(item_id)
    assert res["errors"] == []                                   # validate_card is empty
    card = res["card"]
    unk = card["unknowns"]
    import html as _h

    assert unk and all(f"<code>{_h.escape(u)}</code>" in body for u in unk)  # the page lists every UNKNOWN the card lists (escaped)
    # the page never adds data: nothing is shown as known that the card marks UNKNOWN
    assert card["listing_activity"]["posted_at"]["value"] == "UNKNOWN" and "POSTED" not in body.upper().split("LISTING ACTIVITY")[0]
    assert card["item"]["title"] in body or card["item"]["title"].replace("&", "&amp;") in body


def test_every_receipt_is_in_the_trail_with_provenance_links(rt, discover, ui):
    item_id, areq = ready(rt, discover)
    post(ui, areq, "YES", pin=PIN)
    wait_state(rt.engine, item_id, "ACTED")
    body = item_page(ui, item_id)[2]
    receipts = ui.store.receipts(item_id=item_id)
    assert receipts
    for r in receipts:
        assert r["receipt_id"] in body, r["type"]                  # R17: no invisible autonomous actions
    card = ui.store.opportunity_card(item_id)["card"]
    assert len(card["activity_trail"]) == len(receipts)
    for t in card["activity_trail"]:
        for pid in t["inputs"]:
            assert f"href='/provenance/{pid}'" in body
    assert "CONTACT SENT" in body or "CONTACT APPROVED" in body   # timeline stages with receipts


def test_decision_controls_sit_beneath_the_recommendation_and_return_to_the_card(rt, discover, ui):
    item_id, areq = ready(rt, discover)
    body = item_page(ui, item_id)[2]
    i_rec = body.index("<h2>Recommendation</h2>")
    for btn in (">YES<", ">NO<", ">MODIFY<", ">HOLD<"):
        assert body.index(btn) > i_rec
    assert body.index("Step-up PIN") > i_rec and 'name="return" value="item"' in body
    assert "needs step-up approval" in body                           # the step-up flag is on the recommendation
    s, loc, _ = post(ui, areq, "HOLD", hold_preset="24h", **{"return": "item"})
    assert loc.startswith(f"/item/{item_id}?msg=HOLD recorded"), loc
    wait_state(rt.engine, item_id, "HELD")
    body = item_page(ui, item_id)[2]
    assert "On HOLD" in body and "Wake now" in body
    s, loc, _ = post(ui, areq, "NO", reason="", **{"return": "item"})  # a refused decision also returns to the card
    assert loc.startswith(f"/item/{item_id}?err=")


def test_decisions_remain_a_human_channel(rt, discover, ui):
    item_id, areq = ready(rt, discover)
    r = req(ui, "POST", f"/areq/{areq['action_request_id']}/decide",
            {"decision": "HOLD", "payload_hash_seen": areq["payload_hash"], "return": "item"})
    assert "err=invalid form token" in r[1] and approvals(rt.engine, areq["action_request_id"]) == []
    assert item_page(ui, item_id, host="evil.example")[0] == 403
    # a read-only page: no form posts anywhere except the decision/outcome/wake routes
    actions = set(re.findall(r'<form method="post" action="([^"]+)"', item_page(ui, item_id)[2]))
    assert actions and all(re.fullmatch(r"/areq/areq_\w+/(decide|wake|outcome)", a) for a in actions)


def test_hostile_listing_text_cannot_break_the_page(rt, discover, ui):
    tid = discover("FIX-TRAILER-1", titles={"FIX-TRAILER-1": HOSTILE})["FIX-TRAILER-1"]
    wait_state(rt.engine, tid, "AWAITING_APPROVAL")
    body = item_page(ui, tid)[2]
    assert "<script>alert(1)</script>" not in body and "<img src=x" not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
    assert body.count("<html") == 1 and body.rstrip().endswith("</html>")


def test_enrichment_blocks_render_with_basis_and_hostile_text_escaped(rt, discover, ui):
    item_id, areq = ready(rt, discover)
    with rt.engine.begin() as c:
        prov = tool_provenance(c, "tests.f13.enrichment", agent_name="agent-02-opportunity")
        spine.record_enrichment(c, item_id, "listing_activity", {
            "posted_at": {"value": "2026-10-01T12:00:00Z", "basis": "FACT", "provenance_id": prov},
            "age_days": {"value": 6, "basis": "FACT", "unit": "days"},
            "stale_risk": {"value": "low", "basis": "INFERENCE"},
            "recent_activity": [HOSTILE]}, prov, agent="agent-02-opportunity")
        spine.record_enrichment(c, item_id, "seller", {
            "rating": {"value": 4.8, "basis": "FACT"}, "confidence": "medium"}, prov, agent="agent-02-opportunity")
        spine.record_enrichment(c, item_id, "value_add", {
            "plan": {"value": "Replace the front axle bearings and re-wire the marker lights " + HOSTILE, "basis": "INFERENCE"},
            "model_specific_risks": [{"risk": "Torsion axle lower-seat corrosion on this model year", "basis": "FACT",
                                      "source": "https://example.invalid/forum/thread"}]}, prov, agent="agent-03-economics")
    res = ui.store.opportunity_card(item_id)
    assert res["errors"] == []
    body = item_page(ui, item_id)[2]
    assert "2026-10-01T12:00:00Z" in body and "<span class='tag fact'>FACT</span>" in body
    assert f"href='/provenance/{prov}'" in body
    assert "Torsion axle lower-seat corrosion" in body and "example.invalid/forum/thread" in body
    assert "<script>" not in body and "&lt;script&gt;" in body
    assert "Seller style: UNKNOWN" not in body                   # real seller data replaces the UNKNOWN banner...
    assert "4.8 <span class='tag fact'>FACT</span>" in body        # a valid seller rating is shown (the hardened card drops invalid ones to UNKNOWN)
    assert "Confidence: medium" in body
    ids = [r["receipt_id"] for r in ui.store.receipts(item_id=item_id)]
    assert len(ids) == len(res["card"]["activity_trail"]) and all(i in body for i in ids)  # enrichment shows in the trail


def test_elementary_advice_failing_validate_is_flagged_not_hidden(rt, discover, ui):
    item_id, _ = ready(rt, discover)
    with rt.engine.begin() as c:
        prov = tool_provenance(c, "tests.f13.lint", agent_name="agent-03-economics")
        spine.record_enrichment(c, item_id, "value_add", {
            "plan": {"value": "Check the compression, spark, fuel and oil before buying", "basis": "INFERENCE"}}, prov)
    res = ui.store.opportunity_card(item_id)
    assert res["errors"], "validate_card should reject elementary advice"
    body = item_page(ui, item_id)[2]
    assert "This card failed its own validation" in body and "elementary advice" in body


def test_unknown_item_404_queue_links_to_the_card_and_old_page_still_works(rt, discover, ui):
    assert item_page(ui, "itm_01JA0000000000000000009999")[0] == 404
    item_id, areq = ready(rt, discover)
    assert f'href="/item/{item_id}"' in req(ui, "GET", "/")[2]
    assert req(ui, "GET", f"/areq/{areq['action_request_id']}")[0] == 200   # technical view stays
    assert "Your decision" in item_page(ui, item_id)[2]


def test_outcome_entry_on_the_card_returns_to_the_card(rt, discover, ui):
    item_id, areq = ready(rt, discover)
    post(ui, areq, "YES", pin=PIN)
    wait_state(rt.engine, item_id, "ACTED")
    body = item_page(ui, item_id)[2]
    assert "Record outcome" in body and "No open request is waiting" in body
    s, loc, _ = req(ui, "POST", f"/areq/{areq['action_request_id']}/outcome",
                    {"csrf": ui.csrf, "return": "item", "kind": "flip_sold", "revenue": "2000", "total_cost": "1000"})
    assert loc.startswith(f"/item/{item_id}?msg=Outcome flip_sold recorded"), loc
    assert "CLOSED" in item_page(ui, item_id)[2]


def test_missing_operator_profile_is_a_clear_error_not_a_guess(rt, discover, ui, monkeypatch, tmp_path):
    item_id, _ = ready(rt, discover)
    monkeypatch.setenv("MBOS_OPERATOR_PROFILE", str(tmp_path / "nope.json"))
    s, _, body = item_page(ui, item_id)
    assert s == 503 and "operator profile not found" in body and "MBOS_OPERATOR_PROFILE" in body
    assert req(ui, "GET", "/")[0] == 200


def test_notes_are_unavailable_on_the_reference_backend_and_nothing_is_stored(rt, discover, ui):
    """F-14: notes need lane D. The form says so, and a forged POST is refused with the reason."""
    item_id, _ = ready(rt, discover)
    body = item_page(ui, item_id)[2]
    assert "Add what you know about this model" in body and "Notes need the lane D store" in body and 'name="makes"' not in body
    form = {"csrf": ui.csrf, "pin": PIN, "category": "trailer", "makes": "Big Tex", "models": "10PI", "kind": "known_weakness",
            "statement": "Torsion axle seats rot out by year six on this model.", "basis_of_knowledge": "own experience on this model"}
    s, _, out = req(ui, "POST", f"/item/{item_id}/note", form)
    assert s == 200 and "Note not saved." in out and "operator notes need the lane D store" in out
    assert "Notes need the lane D store" in req(ui, "GET", "/notes")[2]


# ---------------------------------------------------------------- card hardening (07 acceptance F-26..F-38, d35646d)
def test_dry_run_send_is_tagged_and_the_card_never_says_waiting(rt, discover, ui):
    item_id, areq = ready(rt, discover)
    post(ui, areq, "YES", pin=PIN)
    wait_state(rt.engine, item_id, "ACTED")
    res = ui.store.opportunity_card(item_id)
    assert res["errors"] == []
    card = res["card"]
    sent = [t for t in card["status"]["timeline"] if t["stage"] == "CONTACT SENT"]
    assert sent and sent[0].get("dry_run") is True and card["recommendation"]["waiting"] is False
    body = item_page(ui, item_id)[2]
    assert "DRY-RUN: simulated, nothing sent" in body
    assert "WAIT FOR RESPONSE" not in body and "waiting on the seller" not in body.lower()


def _flagged_card(flags, why_prov=None):
    from mbos.card import build_card, load_profile

    item = json.loads((Path(__file__).resolve().parent.parent / "docs/research/contracts/examples/item-flip-trailer.example.json").read_text())
    item["normalized"]["flags"] = flags
    card = build_card(item, [], [], {}, profile=load_profile())
    if why_prov:
        from mbos.hashing import sha256_of

        card["why_provenance"] = why_prov
        card["card_hash"] = sha256_of({k: v for k, v in card.items() if k not in ("generated_at", "card_hash")})  # still a valid card
    return card


def test_flags_warning_is_visible_and_never_hidden():
    from operator_ui import card_view

    card = _flagged_card(["injection_suspected", "needs_review", "underpriced"])
    assert "injection_suspected" in card["item"]["flags"]
    html = card_view.render_item_card(card, [], "")
    assert "WARNING: this listing was flagged" in html and "needs your eyes" in html
    assert "<code>injection_suspected</code>" in html and "<code>needs_review</code>" in html
    assert "WARNING" not in card_view.render_item_card(_flagged_card([]), [], "")


def test_why_provenance_links_and_schema_accepts_the_new_fields():
    from operator_ui import card_view

    pid = "prov_01JA0000000000000000000007"
    card = _flagged_card(["needs_review"], why_prov=[pid])
    assert mc.validate_card(card) == []                       # the re-vendored schema accepts flags + why_provenance
    html = card_view.render_item_card(card, [], "")
    assert f"href='/provenance/{pid}'" in html and "Lane-supplied reasons come from" in html


def test_control_ansi_and_bidi_characters_are_stripped_from_displayed_titles(rt, discover, ui):
    nasty = "Trailer \x1b[31mRED\x1b[0m ‮evil‬\x07 end"
    tid = discover("FIX-TRAILER-1", titles={"FIX-TRAILER-1": nasty})["FIX-TRAILER-1"]
    wait_state(rt.engine, tid, "AWAITING_APPROVAL")
    for path in (f"/item/{tid}", "/", f"/areq/{[a for a in ui.store.action_requests_for_item(tid)][0]['action_request_id']}"):
        body = req(ui, "GET", path)[2]
        assert "\x1b" not in body and "‮" not in body and "‬" not in body and "\x07" not in body, path
    assert "Trailer" in req(ui, "GET", f"/item/{tid}")[2]
