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
