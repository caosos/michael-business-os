"""G-05 / ADR-0011 rule 6 (R18): Michael is an experienced mechanic. Elementary advice in the value-add plan or in the
model-specific risks FAILS unless it is sourced AND model-specific. Judged by `mbos.card.validate_card` on cards built
by `build_card`, with this lane's own phrase list (what a lazy lane or an LLM would actually write)."""
import pytest

from .conftest import world

ELEMENTARY = [
    "Check compression before buying", "check the compression", "Inspect the fuel", "inspect fuel system for varnish",
    "Check engine oil level", "Check the oil", "check the air filter", "Check spark", "check for spark",
    "Check the spark plug", "check the plugs", "Verify it starts", "Make sure it runs", "verify it runs",
    "Make sure the engine starts", "Check the battery", "look for leaks", "Look for any damage",
    "Inspect the belts", "inspect hoses",
    # variations a lane or an LLM would equally write
    "Test compression", "Do a compression test", "Pull the plug and check for spark", "See if it starts",
    "Try starting it", "Check that it starts", "Check the fuel", "Check fuel flow", "Check the carburetor",
    "Check the oil level and condition", "Check tire pressure", "Check the coolant level", "Check the fluids",
    "Inspect the spark plug", "Verify the engine runs", "Make sure it turns over", "Check for oil leaks",
    "Check  compression", "Check\ncompression", "Check compression", "CHECK COMPRESSION", "check-compression",
]


def _card(mc, profile, plan=None, risks=None):
    enr = {}
    if plan is not None:
        enr["value_add"] = {"plan": {"value": plan, "basis": "INFERENCE"}}
    if risks is not None:
        enr.setdefault("value_add", {})["model_specific_risks"] = risks
    return mc.build_card(*world(), enr, profile=profile)


@pytest.mark.parametrize("text", ELEMENTARY, ids=[repr(t) for t in ELEMENTARY])
def test_elementary_advice_in_the_plan_is_rejected(mc, profile, text):
    errs = mc.validate_card(_card(mc, profile, plan=text))
    assert errs, f"elementary advice passed validation as a plan: {text!r}"


@pytest.mark.parametrize("text", ELEMENTARY[:12], ids=[repr(t) for t in ELEMENTARY[:12]])
def test_unsourced_elementary_risk_is_rejected(mc, profile, text):
    r = [{"risk": text, "basis": "INFERENCE", "provenance_id": "prov_" + "0" * 25 + "1"}]
    assert mc.validate_card(_card(mc, profile, risks=r)), f"elementary advice passed as a risk: {text!r}"


def test_sourced_model_specific_knowledge_is_accepted(mc, profile):
    plan = "Replace the recoil starter spring (Honda GCV160, known failure, part 28462-ZL8-023, about $14) and re-time the flywheel key."
    risks = [{"risk": "GCV160 carburetor bowl nut seeps when the gasket hardens; $9 gasket, 20 minutes.", "kind": "known_weakness",
              "basis": "FACT", "source": "Honda GCV160 service manual 4-12"}]
    assert mc.validate_card(_card(mc, profile, plan=plan, risks=risks)) == []


@pytest.mark.parametrize("source", ["n/a", "none", "N/A", "unknown", "-", " ", "todo", "trust me"])
def test_a_junk_source_does_not_launder_elementary_advice(mc, profile, source):
    """'Sourced' must mean a real source. A placeholder string is not one."""
    r = [{"risk": "Check compression before buying", "kind": "known_weakness", "basis": "FACT", "source": source}]
    assert mc.validate_card(_card(mc, profile, risks=r)), f"source={source!r} let elementary advice through"


def test_the_contract_can_mark_content_model_specific(mc, profile):
    """ADR-0011 rule 6: elementary advice is allowed only when a lane 'marks it model-specific with a source'. There must
    be a place to put that mark; otherwise 'sourced' is the only gate and generic advice with any source passes."""
    import json

    from .conftest import CARD_SCHEMA

    risk = CARD_SCHEMA["properties"]["value_add_plan"]["properties"]["model_specific_risks"]["items"]["properties"]
    assert "model_specific" in risk or "model" in risk or "make_model" in risk, \
        f"card.schema.json has no model-specificity marker on risks (kind enum: {risk['kind']['enum']})"
    json.dumps(risk)


def test_generic_advice_with_a_real_looking_source_is_still_generic(mc, profile):
    """With no marker, any source string launders elementary advice."""
    r = [{"risk": "Check compression before buying", "kind": "known_weakness", "basis": "FACT", "source": "Briggs forum post"}]
    assert mc.validate_card(_card(mc, profile, risks=r)), "generic advice was accepted because it carried a source"


def test_a_risk_with_basis_fact_still_needs_a_source_or_provenance(mc, profile):
    r = [{"risk": "Crankshaft keyway shears under load on this model", "basis": "FACT"}]
    assert mc.validate_card(_card(mc, profile, risks=r)), "an unsourced FACT claim was accepted as a model-specific risk"


def test_no_false_positives_on_legitimate_mechanic_language(mc, profile):
    for text in ("Rebuild the Walbro WYL carb (jets 0.032 / 0.034); the batteryless ignition module is the usual fault.",
                 "Replace the primary clutch spring; Cub Cadet RZT50 deck belt is $24 and a 30-minute job.",
                 "Re-pack both wheel bearings and swap the 4.80-12 tires; axle is 3500 lb rated."):
        assert mc.validate_card(_card(mc, profile, plan=text)) == [], text


def test_the_lint_also_covers_the_lane_why_lines(mc, profile):
    """Lane C's `why` is rendered to Michael verbatim; elementary advice there is the same defect."""
    from .conftest import pid

    card = mc.build_card(*world(), {"why": ["Check compression first, then decide."], "_prov": {"why": pid(7)}}, profile=profile)
    assert any("Check compression" in w for w in card["why"]), "the sourced why line is not on the card"
    assert mc.validate_card(card), "elementary advice in a SOURCED `why` line passes validation"
