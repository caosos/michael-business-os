"""F-14: "Add what you know about this model", Michael's own mechanic knowledge on lane D + lane E (human channel only)."""

from __future__ import annotations

import json
import re

import pytest

from mbos_economics.valueadd import _note_problems
from tests.conftest import PIN
from tests.lane_d.test_ui_on_lane_d import q, ready, req, wait

NOTE = {"category": "trailer", "makes": "Big Tex", "models": "10PI, 14ET", "kind": "known_weakness",
        "statement": "Torsion axle lower spring seats corrode through by about year six on this model.",
        "basis_of_knowledge": "own experience on this model", "basis_detail": "owned two, replaced both", "reference_url": ""}


def add(ui, item_id, **over):
    form = {"csrf": ui.csrf, "pin": PIN, **NOTE, **over}
    return req(ui, "POST", f"/item/{item_id}/note", form)


def test_card_prompts_for_model_knowledge_and_the_note_round_trips(rtd, discover_d, ui_d):
    item_id, _ = ready(ui_d, discover_d)
    body = req(ui_d, "GET", f"/item/{item_id}")[2]
    assert "Add what you know about this model" in body and "No sourced model knowledge is on this card" in body
    assert 'name="author"' not in body and 'name="entered_by"' not in body            # the author is never a form field
    i_rec = body.index("<h2>Recommendation</h2>")
    assert body.index("Add what you know about this model") > i_rec
    s, loc, _ = add(ui_d, item_id)
    assert s == 303 and loc.startswith(f"/item/{item_id}?msg=Note saved (mn_"), loc
    (n,) = [x for x in ui_d.store.operator_notes() if x["statement"].startswith("Torsion axle")]
    assert n["entered_by"] == "michael" and n["basis"] == "RECOMMENDATION" and n["match"] == [{"makes": ["Big Tex"], "models": ["10PI", "14ET"]}]
    assert n["basis_of_knowledge"] == "own experience on this model: owned two, replaced both"
    prov = ui_d.store.provenance(n["provenance_id"])
    assert prov["actor_type"] == "human" and prov["human_actor"] == "michael" and prov["basis"] == "RECOMMENDATION"
    rcpts = [r for r in q(rtd, "SELECT doc FROM mbos.v_receipt_documents WHERE doc->>'entity_type' = 'operator_note'")]
    assert rcpts and n["provenance_id"] in json.dumps(rcpts[-1][0])                  # receipted with the human provenance
    page = req(ui_d, "GET", "/notes")[2]
    assert "Torsion axle lower spring seats" in page and "Big Tex" in page and n["provenance_id"] in page


def test_refusals_are_shown_with_every_reason_and_nothing_is_saved(rtd, discover_d, ui_d):
    item_id, _ = ready(ui_d, discover_d)
    before = len(ui_d.store.operator_notes())
    cases = {
        "elementary": ({"statement": "Check the compression and spark first."}, "elementary advice"),
        "no model": ({"models": ""}, "BOTH makes and models"),
        "FACT": ({"basis": "FACT"}, "never FACT"),
        "bad kind": ({"kind": "gossip"}, "must be one of"),
        "bad url": ({"reference_url": "http://example.invalid/x"}, "reference_url must be https"),
        "too long": ({"statement": "x" * 601}, "over 600 characters"),
    }
    for name, (over, reason) in cases.items():
        s, _, body = add(ui_d, item_id, **over)
        assert s == 200 and "Note not saved." in body and reason in body, (name, body[-1500:])
        assert 'name="makes"' in body                                               # the form is re-shown with the typed values
    s, _, body = add(ui_d, item_id, statement="Check the compression.", models="", basis="FACT")
    for reason in ("elementary advice", "BOTH makes and models", "never FACT"):      # all reasons at once
        assert reason in body
    assert len(ui_d.store.operator_notes()) == before


def test_fact_refusal_text_is_the_loaders_own_text():
    from operator_ui.ux import _FACT_REFUSAL

    assert _FACT_REFUSAL in _note_problems({"basis": "FACT"})


def test_human_channel_guards(rtd, discover_d, ui_d):
    item_id, _ = ready(ui_d, discover_d)
    n0 = len(ui_d.store.operator_notes())
    assert req(ui_d, "POST", f"/item/{item_id}/note", {**NOTE, "pin": PIN})[2].count("invalid form token") >= 1      # no CSRF
    assert "PIN is required" in add(ui_d, item_id, pin="0000")[2]
    assert "PIN is required" in add(ui_d, item_id, pin="")[2]
    assert req(ui_d, "POST", f"/item/{item_id}/note", {"csrf": ui_d.csrf, "pin": PIN, **NOTE}, host="evil.example")[0] == 403
    ui_d.operator_pin = None
    try:
        assert "notes are refused (fail-closed)" in add(ui_d, item_id)[2]
    finally:
        ui_d.operator_pin = PIN
    assert len(ui_d.store.operator_notes()) == n0
    # a forged author is ignored: the stored author is always the authenticated operator
    s, loc, _ = add(ui_d, item_id, author="mallory", entered_by="mallory",
                    statement="Rear leaf-spring hangers crack at the weld on this model when overloaded.")
    assert s == 303
    mine = [x for x in ui_d.store.operator_notes() if x["statement"].startswith("Rear leaf-spring hangers")]
    assert mine and all(x["entered_by"] == "michael" for x in mine)
    s, _, body = req(ui_d, "POST", "/item/itm_01JA0000000000000000009999/note", {"csrf": ui_d.csrf, "pin": PIN, **NOTE})
    assert s == 404 and "No such opportunity" in body                                 # nothing is stored for an unknown item


def test_hostile_note_text_is_escaped_everywhere(rtd, discover_d, ui_d):
    item_id, _ = ready(ui_d, discover_d)
    evil = "<script>alert(1)</script>"
    add(ui_d, item_id, makes=f"Big Tex {evil}", models="10PI", statement=f"Frame rails crack near the coupler {evil} on this model.")
    for path in ("/notes", f"/item/{item_id}"):
        body = req(ui_d, "GET", path)[2]
        assert "<script>alert(1)</script>" not in body, path
    assert "&lt;script&gt;" in req(ui_d, "GET", "/notes")[2]


def test_workflows_cannot_reach_the_note_path():
    """R14: the database cannot stop `mbos_dbos` from calling record_operator_note, so the code path must. The UI's
    server and backend are the only callers here; the worker modules never reference it."""
    import pathlib

    import mbos

    root = pathlib.Path(mbos.__file__).parent
    offenders = [str(p.name) for p in root.rglob("*.py") if p.name in ("workflows.py", "runtime.py") and "record_operator_note" in p.read_text()]
    assert offenders == []
    ui = pathlib.Path(__file__).resolve().parents[2] / "operator_ui"
    callers = sorted(p.name for p in ui.glob("*.py") if "record_operator_note(" in p.read_text())
    assert callers == ["backend.py", "server.py"]            # backend defines/calls; server.add_note is the only entry point


def test_note_shows_on_the_next_cards_of_that_model_as_michaels_recommendation(rtd, discover_d, ui_d, monkeypatch):
    """Acceptance: Michael enters a note; it shows on the NEXT card of that make+model with his provenance, after any
    sourced recall. Real lane C engine + EconomicsEnricher (A-21) in the real DBOS workflow."""
    from mbos.adapters.economics import EconomicsEnricher, EconomicsEngineScorer
    from mbos.card import load_profile
    from mbos.runtime import components

    comps = components()
    monkeypatch.setattr(comps, "scorer", EconomicsEngineScorer())
    monkeypatch.setattr(comps, "enrichers", [EconomicsEnricher(load_profile())])
    from operator_ui import ux
    from mbos.clock import now_iso

    bundle = ux.parse_note({**NOTE, "makes": "Acme", "models": "ZX9",
                            "statement": "The ZX9 hitch weld cracks under load; reinforce the gusset before towing."},
                           "michael", now_iso())
    ui_d.store.record_operator_note(bundle)                                         # entered BEFORE the next card exists
    nid = discover_d("FIX-TRAILER-1", titles={"FIX-TRAILER-1": "2016 Acme ZX9 utility trailer, needs lights"})["FIX-TRAILER-1"]
    wait(lambda: ui_d.store.item(nid)["state"] in ("AWAITING_APPROVAL", "RESEARCHING", "ARCHIVED"))
    card = ui_d.store.opportunity_card(nid)["card"]
    mine = [r for r in card["value_add_plan"]["model_specific_risks"] if "ZX9 hitch weld" in r["risk"]]
    assert mine and mine[0]["basis"] == "RECOMMENDATION" and mine[0].get("provenance_id"), card["value_add_plan"]
    prov = ui_d.store.provenance(mine[0]["provenance_id"])
    assert prov["human_actor"] == "michael"
    body = req(ui_d, "GET", f"/item/{nid}")[2]
    assert "ZX9 hitch weld cracks" in body and f"href='/provenance/{mine[0]['provenance_id']}'" in body
    assert "No sourced model knowledge is on this card" in body                    # his note is not a sourced recall
