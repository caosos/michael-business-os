import pytest

from mbos import intake
from mbos.contracts.schemas import ContractViolation


def test_specs_available():
    assert {"mower", "trailer", "home_repair_job"} <= set(intake.available())


def test_missing_questions_are_minimal_ordered_and_safety_first():
    d = intake.new_draft("mower")
    d = intake.answer(d, "operating_status", "runs but smokes")
    d = intake.answer(d, "price_usd", 400)
    qs = intake.missing(d)
    keys = [q["key"] for q in qs]
    assert "operating_status" not in keys and "price_usd" not in keys
    assert keys[0] == "safety_features"                     # safety-relevant first
    assert keys.index("make_model") < keys.index("hours")   # material before non-material


def test_unknown_counts_as_answered_but_stays_unknown():
    d = intake.answer(intake.new_draft("mower"), "hours", "whatever", basis="UNKNOWN")
    assert d["answers"]["hours"] == {"value": "unknown", "basis": "UNKNOWN"}
    assert "hours" not in [q["key"] for q in intake.missing(d)]


def test_verified_cannot_be_set_by_intake():
    with pytest.raises(ContractViolation, match="verified"):
        intake.answer(intake.new_draft("mower"), "make_model", "Brand X", basis="verified")


def test_unknown_field_and_basis_rejected():
    with pytest.raises(ContractViolation):
        intake.answer(intake.new_draft("mower"), "favorite_color", "red")
    with pytest.raises(ContractViolation):
        intake.answer(intake.new_draft("mower"), "hours", 5, basis="trust_me")


def test_photo_angle_questions_clear_when_evidence_supplied():
    d = intake.new_draft("mower")
    assert any(q["key"] == "photo:front" for q in intake.missing(d))
    d = intake.answer(d, "hours", 120, evidence=[{"kind": "photo", "ref": "photo:front-left.jpg"}])
    assert not any(q["key"] == "photo:front" for q in intake.missing(d))


def test_service_job_spec_asks_for_location_for_local_rules():
    keys = [q["key"] for q in intake.missing(intake.new_draft("home_repair_job"))]
    assert "location" in keys and "scope" in keys


def test_facts_carry_basis_unchanged():
    d = intake.answer(intake.new_draft("mower"), "operating_status", "runs but smokes")
    f = intake.to_inventory_facts(d)[0]
    assert f["basis"] == "seller_stated" and f["material"] is True


def test_owned_trailer_spec_keeps_sunk_basis_out_of_the_decision_and_the_tow_unverified():
    spec = intake.load_spec("owned_trailer")
    assert spec["owned_asset"] is True and "SUNK" in spec["note"] and "roadworthy" in spec["note"]
    keys = [f["key"] for f in spec["fields"]]
    assert {"historical_basis_usd", "past_tow", "minimal_rehab_cash", "themed_rehab_cash", "your_hours", "personal_use"} <= set(keys)
    d = intake.answer(intake.new_draft("owned_trailer"), "past_tow", "Towed Little Rock to Conway after new tires", basis="seller_stated")
    assert d["answers"]["past_tow"]["basis"] == "seller_stated"                 # never upgraded to verified
    qs = intake.missing(d)
    assert qs[0]["safety_relevant"] and "past_tow" not in [q["key"] for q in qs]
    assert "historical_basis_usd" in [q["key"] for q in qs]
