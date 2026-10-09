"""F-34: "My assets": the BBQ trailer is added from the owned-trailer spec with Michael's stated facts; the five-path card names the
UNKNOWNs; photo references and the inspection checklist keep their basis; nothing is verified; PIN + CSRF gate the owner channel."""

from __future__ import annotations

from mbos import intake
from operator_ui import assets_view
from tests.conftest import PIN
from tests.test_operator_ui import req

TOW = "Little Rock to Conway, tracked straight"


def add(ui, **kw):
    form = {"csrf": ui.csrf, "pin": PIN, "title": "BBQ trailer", "a_historical_basis_usd": "paid about $4,500 last year", "a_past_tow": TOW, **kw}
    st, loc, _ = req(ui, "POST", "/assets/add", form)
    assert st == 303 and loc.startswith("/assets/asset-")
    return loc.split("?")[0]


def test_acceptance_bbq_trailer_card_lists_five_paths_with_unknowns_and_nothing_verified(ui):
    path = add(ui)
    st, _, body = req(ui, "GET", path)
    assert st == 200 and "BBQ trailer" in body and "Verified facts: 0" in body
    for p in ("SELL_AS_IS_OR_PART_OUT", "MINIMAL_REHAB_FLIP", "THEMED_VALUE_ADD_FLIP", "CONVERT", "KEEP"):
        assert p in body
    assert "owned:minimal:cash" in body and "owned:keep:value" in body and "owned:tailgate_months" in body   # UNKNOWNs named
    assert "nothing is recommended" in body                                                                   # no invented figures
    assert "INFERENCE" in body and "$4,500" in body and "excluded from net" in body                           # tow is inference; basis is sunk
    asset = next(iter(ui.assets.values()))
    assert asset["answers"]["past_tow"] == {"value": TOW, "basis": "seller_stated"}
    assert "verified" not in {a["basis"] for a in asset["answers"].values()} and ">verified<" not in body


def test_checklist_keeps_basis_verified_is_refused_photos_are_references(ui):
    path = add(ui)
    aid = path.split("/")[-1]
    f = {"csrf": ui.csrf, "pin": PIN, "a_tires": "<b>dry rotted</b>", "b_tires": "stated", "a_structure": "looks fine", "b_structure": "inferred",
         "a_suspension": "x", "b_suspension": "unknown"}
    assert req(ui, "POST", f"/assets/{aid}/answer", f)[0] == 303
    a = ui.assets[aid]["answers"]
    assert a["tires"]["basis"] == "seller_stated" and a["structure"]["basis"] == "system_inferred" and a["suspension"]["basis"] == "UNKNOWN"
    body = req(ui, "GET", path)[2]
    assert "<b>dry rotted</b>" not in body and "&lt;b&gt;dry rotted" in body and "PARTIAL" in body
    st, _, body = req(ui, "POST", f"/assets/{aid}/answer", {**f, "a_burners_work": "ok", "b_burners_work": "verified"})
    assert st == 200 and "cannot be set by intake" in body and "burners_work" not in ui.assets[aid]["answers"]
    assert req(ui, "POST", f"/assets/{aid}/answer", {"csrf": ui.csrf, "pin": PIN, "p_photo": "rear.jpg\ntongue and coupler.jpg"})[0] == 303
    assert [x["ref"] for x in ui.assets[aid]["evidence"]] == ["rear.jpg", "tongue and coupler.jpg"]
    assert "photo ref, unverified" in req(ui, "GET", path)[2]
    assert all(x["kind"] == "photo" for x in ui.assets[aid]["evidence"])


def test_owner_channel_needs_csrf_and_pin(ui):
    base = {"title": "BBQ trailer", "a_past_tow": TOW}
    assert "invalid form token" in req(ui, "POST", "/assets/add", {**base, "csrf": "bad", "pin": PIN})[2]
    assert req(ui, "POST", "/assets/add", {**base, "csrf": ui.csrf, "pin": "0000"})[0] == 200
    assert req(ui, "POST", "/assets/add", {**base, "csrf": ui.csrf})[0] == 200
    assert not ui.assets
    assert req(ui, "POST", "/assets/asset-nope/answer", {"csrf": ui.csrf, "pin": PIN})[0] == 404
    assert req(ui, "GET", "/assets")[0] == 200


def test_figures_the_owner_gave_move_a_path_and_unknown_answers_stay_missing():
    d = assets_view.add("T", {"a_minimal_rehab_cash": "$200-400", "a_past_tow": "x", "b_past_tow": "unknown"})
    item = assets_view.to_item("asset-1", d, "human:operator")
    fields = {r["field"]: r for r in item["research"]}
    assert fields["owned:minimal:cash"]["value"] == {"low": 200.0, "high": 400.0} and "owned:past_tow" not in fields
    assert all(r["basis"] in ("FACT", "INFER") and r["provenance_id"].startswith("prov_") for r in item["research"])
    assert intake.load_spec("owned_trailer")["owned_asset"] is True
