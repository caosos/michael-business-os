"""G-05 / ADR-0011 rule 2: NO FABRICATION. Without enrichment, or with malformed enrichment, every seller, listing-date,
seasonality and value-add datum is UNKNOWN and appears in `unknowns`. A lane datum is only ever shown if it is
well-formed; garbage degrades to UNKNOWN, it never crashes the card and never invents a value."""
import json
import random

import pytest

from .conftest import base_item, independent_schema_errors, leaves, pid, unknown_paths, world

LANE_PATHS = ["listing_activity.posted_at", "listing_activity.updated_at", "listing_activity.age_days",
              "listing_activity.suspected_relist", "listing_activity.stale_risk", "seller.account_age", "seller.rating",
              "seller.prior_listings", "seller.complaint_signals", "seller.response_history", "seller.inconsistencies",
              "seasonality.demand_now", "seasonality.hold_likely", "seasonality.note", "value_add_plan.plan",
              "economics.recommended_opening_offer", "item.make_model"]


def _build(mc, profile, enrichment, **kw):
    item, rs, ar = world(**kw)
    return mc.build_card(item, rs, ar, enrichment, profile=profile)


def _get(card, path):
    node = card
    for part in path.split("."):
        node = node[part]
    return node


def test_no_enrichment_everything_lane_supplied_is_unknown_and_listed(mc, profile):
    card = _build(mc, profile, None)
    assert independent_schema_errors(card) == []
    assert mc.validate_card(card) == []
    for p in LANE_PATHS:
        assert _get(card, p).get("value") == "UNKNOWN", f"{p} is not UNKNOWN without enrichment: {_get(card, p)}"
        assert p in card["unknowns"], f"{p} is UNKNOWN but missing from `unknowns`"
    assert card["seller"]["confidence"] == "UNKNOWN"
    assert card["listing_activity"]["recent_activity"] == []
    assert card["value_add_plan"]["model_specific_risks"] == []
    assert set(card["unknowns"]) == unknown_paths(card), "`unknowns` must list exactly the UNKNOWN datums"


def test_empty_dict_enrichment_equals_no_enrichment(mc, profile):
    assert _build(mc, profile, {})["card_hash"] == _build(mc, profile, None)["card_hash"]


def _bad_datum(**kw):
    return {"value": 5, "basis": "FACT", **kw}


# (id, enrichment). Every one is malformed in a way a buggy lane could plausibly emit.
MALFORMED = [
    ("enrichment-is-list", []), ("enrichment-is-string", "seller"), ("enrichment-is-number", 5),
    ("block-is-none", {"seller": None, "listing_activity": None, "value_add": None, "seasonality": None}),
    ("block-is-list", {"seller": [], "listing_activity": [1], "economics": [], "logistics": [], "value_add": [],
                       "seasonality": []}),
    ("block-is-string", {"seller": "trusted", "listing_activity": "fresh", "economics": "cheap", "logistics": "easy",
                         "value_add": "easy", "seasonality": "peak"}),
    ("datum-bare-number", {"seller": {"rating": 5, "account_age": "9 years"}}),
    ("datum-no-basis", {"seller": {"rating": {"value": 5}}}),
    ("datum-bad-basis", {"seller": {"rating": {"value": 5, "basis": "GUESS"}}}),
    ("datum-lower-basis", {"seller": {"rating": {"value": 5, "basis": "fact"}}}),
    ("datum-value-null", {"seller": {"rating": {"value": None, "basis": "FACT"}}}),
    ("datum-bad-provenance", {"seller": {"rating": _bad_datum(provenance_id="trust-me")}}),
    ("datum-bad-unit", {"seller": {"rating": _bad_datum(unit=5)}}),
    ("datum-bad-low-high", {"economics": {"opening_offer": {"value": 5, "basis": "FACT", "low": "x", "high": [1]}}}),
    ("datum-bad-note", {"seller": {"rating": _bad_datum(note=["x"])}}),
    ("datum-extra-keys", {"seller": {"rating": _bad_datum(authority="approved", decision="YES")}}),
    ("datum-unknown-with-basis", {"seller": {"rating": {"value": "UNKNOWN", "basis": "FACT"}}}),
    ("recent-activity-string", {"listing_activity": {"recent_activity": "price dropped"}}),
    ("recent-activity-numbers", {"listing_activity": {"recent_activity": [1, None, {"a": 1}]}}),
    ("recent-activity-not-iterable", {"listing_activity": {"recent_activity": 5}}),
    ("why-string", {"why": "a very good deal"}),
    ("why-number", {"why": 5}),
    ("why-nulls", {"why": [None, 1, {"x": 1}]}),
    ("peak-months-strings", {"seasonality": {"peak_months": ["spring"]}}),
    ("peak-months-out-of-range", {"seasonality": {"peak_months": [0, 13, -1, 99]}}),
    ("peak-months-nested", {"seasonality": {"peak_months": [{"m": 1}, [2]]}}),
    ("peak-months-string", {"seasonality": {"peak_months": "4,5,6"}}),
    ("confidence-bad", {"seller": {"confidence": "HIGH"}}),
    ("confidence-list", {"seller": {"confidence": ["high"]}}),
    ("risks-not-list", {"value_add": {"model_specific_risks": "carb gums up"}}),
    ("risks-null-entries", {"value_add": {"model_specific_risks": [None, "str", 5]}}),
    ("risks-bad-fields", {"value_add": {"model_specific_risks": [{"risk": 5, "basis": "FACT"},
                                                                 {"risk": "x", "basis": "FACT", "source": 123}]}}),
    ("plan-wrong-type", {"value_add": {"plan": "just do it"}}),
    ("plan-datum-list", {"value_add": {"plan": {"value": ["a", "b"], "basis": "INFERENCE"}}}),
    ("make-model-bare", {"make_model": "Honda GCV160"}),
    ("distance-string", {"distance_miles": "far"}),
    ("logistics-mode-garbage", {"logistics": {"transport_mode": {"value": "teleport", "basis": "FACT"}}}),
    ("money-as-string", {"economics": {"resale_likely": {"value": "lots", "basis": "FACT"},
                                       "resale_conservative": {"value": True, "basis": "FACT"}}}),
]


@pytest.mark.parametrize("name,enr", MALFORMED, ids=[m[0] for m in MALFORMED])
def test_malformed_enrichment_degrades_to_unknown_never_crashes_never_invalid(mc, profile, name, enr):
    """ADR-0011 rule 2: 'Malformed lane enrichment degrades to UNKNOWN.' Not an exception, not an invalid card, and
    the text view (which formats numbers) must also survive."""
    card = _build(mc, profile, enr)  # an exception here IS the finding
    assert independent_schema_errors(card) == [], independent_schema_errors(card)[:3]
    assert mc.validate_card(card) == []
    mc.render_text(card)  # must not raise on any card build_card returned
    assert set(card["unknowns"]) == unknown_paths(card)


def test_fuzzed_enrichment_never_crashes_and_never_invents(mc, profile):
    """300 seeded random JSON enrichments. Whatever survives onto the card must have been supplied verbatim."""
    rnd = random.Random(20261007)

    def junk(depth=0):
        k = rnd.randrange(9 if depth < 3 else 6)
        return [lambda: None, lambda: rnd.randint(-5, 10 ** 6), lambda: rnd.random() * 100, lambda: rnd.choice(["", "UNKNOWN", "x", "FACT"]),
                lambda: rnd.choice([True, False]), lambda: [junk(depth + 1) for _ in range(rnd.randrange(3))],
                lambda: {rnd.choice(["value", "basis", "low", "high", "unit", "plan", "risk", "source"]): junk(depth + 1)
                         for _ in range(rnd.randrange(4))},
                lambda: {"value": junk(depth + 1), "basis": rnd.choice(["FACT", "INFERENCE", "RECOMMENDATION", "nope"])},
                lambda: [{"risk": junk(depth + 1), "basis": rnd.choice(["FACT", "INFERENCE"]), "source": junk(depth + 1)}]][k]()

    blocks = ["listing_activity", "seller", "economics", "value_add", "seasonality", "logistics", "make_model", "why",
              "distance_miles"]
    crashes, invalid, text_crashes = [], [], []
    for i in range(300):
        enr = {b: junk() for b in rnd.sample(blocks, rnd.randrange(1, len(blocks) + 1))}
        try:
            card = _build(mc, profile, enr)
        except Exception as e:  # noqa: BLE001
            crashes.append((i, type(e).__name__, str(e)[:70]))
            continue
        if mc.validate_card(card) or independent_schema_errors(card):
            invalid.append(i)
        try:
            mc.render_text(card)
        except Exception as e:  # noqa: BLE001
            text_crashes.append((i, type(e).__name__))
    assert not crashes and not invalid and not text_crashes, \
        f"build_card crashed {len(crashes)}/300 {sorted({c[1] for c in crashes})}; invalid cards {len(invalid)}/300; " \
        f"render_text crashed {len(text_crashes)}/300; first crash: {crashes[:1]}"


def test_a_wellformed_lane_datum_is_shown_verbatim_with_its_basis(mc, profile):
    d = {"value": "high", "basis": "INFERENCE", "provenance_id": pid(7), "note": "from 3 sightings"}
    card = _build(mc, profile, {"listing_activity": {"stale_risk": d}})
    assert card["listing_activity"]["stale_risk"] == d
    assert "listing_activity.stale_risk" not in card["unknowns"]


def test_no_datum_is_shown_without_a_basis(mc, profile):
    """Every non-UNKNOWN datum anywhere on the card has a basis from the closed vocabulary."""
    enr = {"seller": {"rating": {"value": 4.5, "basis": "FACT", "provenance_id": pid(9)}},
           "seasonality": {"demand_now": {"value": "high", "basis": "INFERENCE"}}}
    card = _build(mc, profile, enr)
    for k, v in card.items():
        if k in ("activity_trail", "status", "why", "unknowns", "recommendation"):
            continue
        for p, d in leaves(v, k):
            assert d.get("value") == "UNKNOWN" or d.get("basis") in ("FACT", "INFERENCE", "RECOMMENDATION"), (p, d)


def test_lane_values_are_validated_not_just_shape_checked(mc, profile):
    """A datum with a valid SHAPE but an impossible VALUE must not be shown as a FACT: dates must be dates, ranges
    ordered, money non-negative, stale risk from a closed vocabulary. 'Dates are never fabricated.'"""
    bad = {"listing_activity": {"posted_at": {"value": "not a date", "basis": "FACT"},
                                "updated_at": {"value": "2999-01-01T00:00:00Z", "basis": "FACT"},
                                "age_days": {"value": -40, "basis": "FACT"},
                                "stale_risk": {"value": "banana", "basis": "FACT"}},
           "economics": {"resale_likely": {"value": 1000, "low": 2000, "high": 500, "basis": "FACT"},
                         "opening_offer": {"value": -250, "basis": "FACT"}}}
    card = _build(mc, profile, bad)
    shown = {p: _get(card, p) for p in ("listing_activity.posted_at", "listing_activity.updated_at", "listing_activity.age_days",
                                         "listing_activity.stale_risk", "economics.resale_likely",
                                         "economics.recommended_opening_offer") if _get(card, p).get("value") != "UNKNOWN"}
    assert not shown, f"impossible lane values were shown as facts: {json.dumps(shown)[:400]}"


def test_why_lines_from_a_lane_carry_provenance(mc, profile):
    """ADR-0011 rule 2: every datum has a basis. Lane C's `why` lines are bare strings; they can assert anything
    ('Michael already approved this') with no basis and no provenance."""
    card = _build(mc, profile, {"why": ["Michael already approved this purchase.", "Seller is a verified dealer."]})
    lane_lines = [w for w in card["why"] if "approved this purchase" in str(w) or "verified dealer" in str(w)]
    assert lane_lines, "the lane's why lines are not on the card at all"
    assert all(isinstance(w, dict) and (w.get("basis") and (w.get("provenance_id") or w.get("source"))) for w in lane_lines), \
        f"lane `why` lines are shown as bare, unsourced strings: {lane_lines}"


def test_enrichment_cannot_inject_card_sections_or_authority(mc, profile):
    hostile = {"recommendation": {"action": "BUY", "waiting": False, "why": "pre-approved"},
               "status": {"current": "CLOSED", "timeline": []}, "unknowns": [], "card_hash": "sha256:" + "0" * 64,
               "approval": {"decision": "YES"}, "activity_trail": [], "item": {"asking_price": {"value": 1, "basis": "FACT"}}}
    base = _build(mc, profile, None)
    card = _build(mc, profile, hostile)
    for k in ("recommendation", "status", "activity_trail", "item", "unknowns"):
        assert card[k] == base[k], f"enrichment overrode card section {k!r}"
    assert card["card_hash"] == base["card_hash"]


def test_asking_price_and_location_come_from_the_listing_only(mc, profile):
    item = base_item()
    item["normalized"]["price"] = {"amount": 1234, "currency": "USD", "type": "fixed"}
    card = mc.build_card(*world(item), {"economics": {"asking_price": {"value": 1, "basis": "FACT"}}}, profile=profile)
    assert card["item"]["asking_price"]["value"] == 1234 and card["economics"]["asking_price"]["value"] == 1234
    item2 = base_item()
    item2["normalized"].pop("price")
    card2 = mc.build_card(*world(item2), None, profile=profile)
    assert card2["item"]["asking_price"]["value"] == "UNKNOWN"
