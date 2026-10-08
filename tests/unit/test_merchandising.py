import copy
import json

import pytest

from mbos import merchandising as mer
from mbos.contracts.schemas import ContractViolation, contracts_dir
from mbos.hashing import sha256_of

EX = contracts_dir() / "examples" / "inventory"
INV = json.loads((EX / "mower.example.json").read_text())
VIEWS = {p.name: json.loads(p.read_text()) for p in EX.glob("mower-view-*.json")}


def view(name="mower-view-mechanic.example.json"):
    return copy.deepcopy(VIEWS[name])


def test_inventory_example_is_valid():
    assert mer.inventory_errors(INV) == []


@pytest.mark.parametrize("name", sorted(VIEWS))
def test_four_truthful_audience_views_pass(name):
    assert mer.lint(INV, VIEWS[name]) == []
    mer.validate(INV, VIEWS[name])


def test_reordering_and_emphasis_are_allowed():
    v = view()
    v["facts"] = list(reversed(v["facts"]))
    v["facts"][0]["emphasis"] = True
    assert mer.lint(INV, v) == []


def _rehash(inv, v):
    v["inventory_hash"] = sha256_of(inv)
    return v


@pytest.mark.parametrize("mut,frag", [
    (lambda v: v.update(disclosures=[]), "not disclosed"),
    (lambda v: v["disclosures"][0].update(text="Engine runs a little rough"), "reworded"),
    (lambda v: v["disclosures"].append({"defect_id": "d9", "text": "x"}), "invented"),
    (lambda v: v["terms"].update(price_usd=300), "terms differ"),
    (lambda v: v.update(headline="Like new riding mower"), "overstates"),
    (lambda v: v.update(body="Runs great, no smoke, no problems."), "overstates"),
    (lambda v: v.update(body="Verified and inspected, ready to mow."), "claims verification"),
    (lambda v: v["facts"][0].update(basis="verified"), "upgrade"),
    (lambda v: v["facts"].pop(0) and None, "material fact"),
    (lambda v: v["facts"].append({"fact_id": "f9", "basis": "verified"}), "invented"),
    (lambda v: v.update(inventory_hash="sha256:" + "0" * 64), "stale or altered"),
    (lambda v: v.update(audience="everyone"), "everyone"),
    (lambda v: v.update(inventory_id="inv_01J9Z00000000000000000AAAA"), "different inventory"),
])
def test_untruthful_views_are_rejected(mut, frag):
    v = view()
    mut(v)
    errs = mer.lint(INV, v)
    assert errs and any(frag in e for e in errs), errs


def test_unknown_fact_cannot_be_presented_as_known_and_material_unknown_must_show():
    inv = copy.deepcopy(INV)
    inv["facts"][2]["material"] = True          # hours is now a material unknown
    v = _rehash(inv, view())
    assert mer.lint(inv, v) == []
    v["facts"][2]["basis"] = "seller_stated"
    assert any("basis changed" in e for e in mer.lint(inv, v))
    v = _rehash(inv, view())
    v["facts"] = [f for f in v["facts"] if f["fact_id"] != "f3"]
    assert any("material fact f3" in e for e in mer.lint(inv, v))


def test_provenance_must_be_kept_on_verified_facts():
    inv = copy.deepcopy(INV)
    inv["facts"][0].update(basis="verified", provenance_id="prov_01J9Z0000000000000000000A1")
    assert mer.inventory_errors(inv) == []
    v = _rehash(inv, view())
    v["facts"][1]["basis"] = "verified"  # f1 lives at index 1 in this view
    assert mer.lint(inv, v)                # basis/provenance mismatch
    v2 = _rehash(inv, view())
    for f in v2["facts"]:
        if f["fact_id"] == "f1":
            f["basis"] = "verified"        # right basis, provenance dropped
    assert any("provenance dropped" in e for e in mer.lint(inv, v2))


def test_verified_without_provenance_is_an_invalid_inventory():
    inv = copy.deepcopy(INV)
    inv["facts"][0]["basis"] = "verified"
    assert any("requires provenance_id" in e for e in mer.inventory_errors(inv))


def test_verification_words_allowed_when_something_is_verified():
    inv = copy.deepcopy(INV)
    inv["facts"][0].update(basis="verified", provenance_id="prov_01J9Z0000000000000000000A1")
    v = _rehash(inv, view())
    for f in v["facts"]:
        if f["fact_id"] == "f1":
            f.update(basis="verified", provenance_id="prov_01J9Z0000000000000000000A1")
    v["body"] += " Make and model verified against the data plate."
    assert mer.lint(inv, v) == []


def test_validate_raises():
    v = view()
    v["disclosures"] = []
    with pytest.raises(ContractViolation):
        mer.validate(INV, v)


DEFECT = "Engine smokes blue under load"


def _with_body(extra, *, headline=None):
    v = view()
    v["body"] = f"{DEFECT}. {extra}"
    if headline:
        v["headline"] = headline
    return v


@pytest.mark.parametrize("extra", [
    "Runs when it wants to. Sold as is, minor cosmetic smoke.",
    "Just needs a tune-up.", "Just needs a little carb cleaning.", "Easy fix.", "Small repair and it is good to go.",
    "Minor issues only.", "Has some character.", "Well maintained and ready to mow.", "Runs good.", "Works great.",
    "Turnkey.", "Barely smokes.", "Cosmetic smoke only.", "Only a little smoke.", "Good running condition.", "Runs strong.",
])
def test_f59_euphemisms_for_a_material_defect_are_rejected(extra):
    errs = mer.lint(INV, _with_body(extra))
    assert any("overstates" in e or "operating-condition" in e for e in errs), (extra, errs)


@pytest.mark.parametrize("extra", [
    "Like new.", "Like new.", "Like  new.", "Li​ke new.", "Like n‍ew.", "L1ke n3w.", "likе new.",   # Cyrillic е
    "N0thing wr0ng.", "nοthing wrong.", "Μint condition.",
])
def test_f59_obfuscated_overclaims_are_rejected(extra):
    errs = mer.lint(INV, _with_body(extra))
    assert any("overstates" in e for e in errs), (extra, errs)


def test_f60_material_defect_must_be_in_the_prose():
    v = view()
    v["body"] = "A fine riding mower."
    v["headline"] = "Riding mower for sale"
    assert any("not stated verbatim" in e for e in mer.lint(INV, v))


def test_f60_ready_to_work_label_invalid_with_material_defect():
    v = view()
    v["label"] = "Ready to Work"
    assert any("claims readiness" in e for e in mer.lint(INV, v))


def test_the_honest_statement_of_a_defect_is_not_an_overclaim():
    inv = copy.deepcopy(INV)
    inv["defects"][0]["text"] = "Only a little power at idle"       # contains an overclaim phrase as an honest defect statement
    v = _rehash(inv, view())
    v["disclosures"][0]["text"] = inv["defects"][0]["text"]
    v["body"] = "Seller says: Only a little power at idle. Hours unknown."
    assert mer.lint(inv, v) == []


def test_f61_severity_downgrade_or_deletion_is_caught_by_the_baseline_check():
    softer = copy.deepcopy(INV)
    softer["defects"][0]["severity"] = "minor"
    assert any("severity lowered" in e for e in mer.revision_errors(INV, softer))
    gone = copy.deepcopy(INV)
    gone["defects"] = []
    assert any("deleted without resolved_defects" in e for e in mer.revision_errors(INV, gone))
    gone["resolved_defects"] = [{"id": "d1", "resolved_by_provenance_id": "prov_01J9Z0000000000000000000A1"}]
    assert mer.revision_errors(INV, gone) == []
    v = _rehash(gone, view())
    v["disclosures"] = []
    v["body"] = "Runs great."
    assert any("severity lowered" in e or "deleted" in e for e in mer.lint(softer, _rehash(softer, view()), baseline=INV))


def test_f62_verification_words_need_the_specific_fact_verified():
    inv = copy.deepcopy(INV)
    inv["facts"][0].update(basis="verified", provenance_id="prov_01J9Z0000000000000000000A1")   # only make_model is verified
    v = _rehash(inv, view())
    for f in v["facts"]:
        if f["fact_id"] == "f1":
            f.update(basis="verified", provenance_id="prov_01J9Z0000000000000000000A1")
    v["body"] = f"{DEFECT}. Tested and working."
    assert any("operating" in e or "verification" in e for e in mer.lint(inv, v))
    v["body"] = f"{DEFECT}. Engine hours verified."
    assert any("verification" in e for e in mer.lint(inv, v))


def test_a35_defect_cannot_vanish_even_without_a_baseline():
    inv = copy.deepcopy(INV)
    inv["defects"] = []                      # deleted, but still listed in defect_ids_seen
    assert any("cannot vanish" in e for e in mer.inventory_errors(inv))
    inv["resolved_defects"] = [{"id": "d1", "resolved_by_provenance_id": "prov_01J9Z0000000000000000000A1"}]
    assert mer.inventory_errors(inv) == []


def test_a35_view_cannot_invent_provenance():
    v = view()
    for f in v["facts"]:
        if f["fact_id"] == "f1":
            f["provenance_id"] = "prov_01J9Z0000000000000000000A1"
    assert any("invented by the view" in e for e in mer.lint(INV, v))
