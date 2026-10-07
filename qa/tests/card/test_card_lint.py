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


def blocked(mc, card, needle: str) -> bool:
    """The elementary advice does not reach Michael: either validation rejects the card, or the text is not on it.
    (01's F-27 fix DROPS uncheckable risks instead of leaving an invalid FACT; that is at least as strict.)"""
    if mc.validate_card(card):
        return True
    shown = [str(card["value_add_plan"]["plan"].get("value", ""))] + [r["risk"] for r in card["value_add_plan"]["model_specific_risks"]] \
        + [str(w) for w in card["why"]]
    return not any(needle.lower() in x.lower() for x in shown)


def _card(mc, profile, plan=None, risks=None):
    enr = {}
    if plan is not None:
        enr["value_add"] = {"plan": {"value": plan, "basis": "INFERENCE"}}
    if risks is not None:
        enr.setdefault("value_add", {})["model_specific_risks"] = risks
    return mc.build_card(*world(), enr, profile=profile)


@pytest.mark.parametrize("text", ELEMENTARY, ids=[repr(t) for t in ELEMENTARY])
def test_elementary_advice_in_the_plan_is_rejected(mc, profile, text):
    assert blocked(mc, _card(mc, profile, plan=text), text), f"elementary advice reached Michael as a plan: {text!r}"


@pytest.mark.parametrize("text", ELEMENTARY[:12], ids=[repr(t) for t in ELEMENTARY[:12]])
def test_unsourced_elementary_risk_is_rejected(mc, profile, text):
    r = [{"risk": text, "basis": "INFERENCE", "provenance_id": "prov_" + "0" * 25 + "1"}]
    assert blocked(mc, _card(mc, profile, risks=r), text), f"elementary advice reached Michael as a risk: {text!r}"


def test_sourced_model_specific_knowledge_is_accepted(mc, profile):
    plan = "Replace the recoil starter spring (Honda GCV160, known failure, part 28462-ZL8-023, about $14) and re-time the flywheel key."
    risks = [{"risk": "GCV160 carburetor bowl nut seeps when the gasket hardens; $9 gasket, 20 minutes.", "kind": "known_weakness",
              "basis": "FACT", "source": "Honda GCV160 service manual 4-12"}]
    assert mc.validate_card(_card(mc, profile, plan=plan, risks=risks)) == []


@pytest.mark.parametrize("source", ["n/a", "none", "N/A", "unknown", "-", " ", "todo", "trust me"])
def test_a_junk_source_does_not_launder_elementary_advice(mc, profile, source):
    """'Sourced' must mean a real source. A placeholder string is not one."""
    r = [{"risk": "Check compression before buying", "kind": "known_weakness", "basis": "FACT", "source": source}]
    assert blocked(mc, _card(mc, profile, risks=r), "Check compression"), f"source={source!r} let elementary advice through"


def test_with_no_exemption_path_nothing_elementary_can_pass(mc, profile):
    """ADR-0011 as amended by Agent 01: the card contract has no model-specific marker, so NOTHING elementary-phrased can
    pass (deliberately stricter than the earlier wording; an exception needs a contract field, ADR-0009). Hold it to that:
    not with a source, not with a provenance id, not as FACT."""
    for basis, extra in (("FACT", {"kind": "known_weakness", "source": "Honda GCV160 service manual section 4-12"}),
                         ("INFERENCE", {"provenance_id": "prov_" + "0" * 25 + "1"}), ("RECOMMENDATION", {"source": "https://example.invalid/m"})):
        r = [{"risk": "Check compression before buying", "basis": basis, **extra}]
        assert blocked(mc, _card(mc, profile, risks=r), "Check compression"), (basis, extra)


def test_a_rejected_lane_claim_leaves_a_trace_on_the_card(mc, profile):
    """A silently dropped claim hides a misbehaving lane. The card must say N lane claim(s) were rejected."""
    r = [{"risk": "Check compression before buying", "basis": "INFERENCE", "provenance_id": "prov_" + "0" * 25 + "1"},
         {"risk": "Check the fluids", "basis": "FACT", "kind": "known_weakness", "source": "Honda GCV160 service manual 4-12"}]
    card = _card(mc, profile, risks=r)
    assert any("rejected" in u for u in card["unknowns"]), f"no trace of the rejected claims in unknowns: {card['unknowns']}"
    clean = _card(mc, profile, risks=[{"risk": "GCV160 carburetor bowl nut seeps when the gasket hardens; $9 gasket", "basis": "FACT",
                                       "kind": "known_weakness", "source": "Honda GCV160 service manual section 4-12"}])
    assert not any("rejected" in u for u in clean["unknowns"]), "a clean card must not claim rejections"


def test_generic_advice_with_a_real_looking_source_is_still_generic(mc, profile):
    """With no marker, any source string launders elementary advice."""
    r = [{"risk": "Check compression before buying", "kind": "known_weakness", "basis": "FACT", "source": "Briggs forum post"}]
    assert blocked(mc, _card(mc, profile, risks=r), "Check compression"), "generic advice reached Michael because it carried a source"


def test_a_risk_with_basis_fact_still_needs_a_source_or_provenance(mc, profile):
    r = [{"risk": "Crankshaft keyway shears under load on this model", "basis": "FACT"}]
    assert blocked(mc, _card(mc, profile, risks=r), "Crankshaft keyway"), "an unsourced FACT claim reached Michael as a model-specific risk"


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
    assert blocked(mc, card, "Check compression"), "elementary advice in a SOURCED `why` line reaches Michael"
