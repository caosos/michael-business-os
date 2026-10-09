"""A-47: the BBQ trailer (only Michael's stated facts) through the real assembly: spine ingest, lane C scorer + enricher, card."""

from __future__ import annotations

import pytest

from mbos import card as cardmod
from mbos import intake, owned_asset, spine
from mbos.runtime import Components

pytest.importorskip("mbos_economics.owned_asset")
NOW = "2026-10-08T12:00:00Z"
PATHS = ["SELL_AS_IS_OR_PART_OUT", "MINIMAL_REHAB_FLIP", "THEMED_VALUE_ADD_FLIP", "CONVERT", "KEEP"]


def _draft(**extra):
    d = intake.new_draft("owned_trailer")
    d["title"] = "BBQ trailer"
    for k, v in {"historical_basis_usd": "paid about $4,000", "past_tow": "Towed Little Rock to Conway after new tires", **extra}.items():
        d = intake.answer(d, k, v, "seller_stated")
    return d


def _run(engine, draft):
    from dataclasses import asdict

    from mbos.adapters.economics import EconomicsEngineScorer, EconomicsEnricher

    comps = Components().with_defaults()
    raw, norm = owned_asset.ingest_pair("asset-bbq1", draft, NOW)
    with engine.begin() as c:
        iid = spine.ingest(c, raw, norm, "owned-intake", "1", comps)["item_id"]
    with engine.begin() as c:
        assert owned_asset.attach_inputs(c, iid, draft, "michael") == len(owned_asset.answers_to_inputs(draft))
    with engine.begin() as c:
        item = spine.read_item(c, iid)
    assert owned_asset.is_owned(item) and item["type"] == "flip"
    sr = EconomicsEngineScorer().score(item)
    assert sr.verdict == "MAYBE" and "five paths" in sr.rationale[0]
    with engine.begin() as c:
        spine.record_score(c, iid, asdict(sr))
    with engine.begin() as c:
        assert EconomicsEnricher().enrich(c, spine, iid) == 1
    with engine.begin() as c:
        assert EconomicsEnricher().enrich(c, spine, iid) == 1  # idempotent: same content, no second block
    with engine.connect() as c:
        item, receipts, areqs = cardmod.load_inputs(c, iid)
        return cardmod.build_card(item, receipts, areqs, cardmod.enrichment_from_item(c, item))


def test_bbq_trailer_stated_facts_only_renders_five_paths_with_named_unknowns(ledger_db):
    card = _run(ledger_db, _draft(tires="new tires last year", structure="frame looks solid"))
    assert cardmod.validate_card(card) == [], cardmod.validate_card(card)
    v = card["value_add_plan"]["plan"]["value"]
    assert [p["path"] for p in v["paths"]] == PATHS
    assert v["recommendation"]["path"] == "UNKNOWN" and v["verified_facts"] == 0
    assert v["sunk_basis"]["historical_basis_usd"]["high"] == 4000 and all(p["net_incremental"] is None for p in v["paths"])
    assert v["roadworthiness"]["confidence"] == "PARTIAL"
    for name in ("owned:minimal:resale", "owned:themed:cash", "owned:keep:value", "owned:tailgate_months", "owned:suspension"):
        assert f"owned_asset: {name}" in card["unknowns"], name
    assert card["value_add_plan"]["plan"]["basis"] == "INFERENCE"


def test_past_tow_alone_stays_inference_and_basis_is_not_in_any_path(ledger_db):
    a = _run(ledger_db, _draft())["value_add_plan"]["plan"]["value"]
    assert a["roadworthiness"]["confidence"] == "PARTIAL" or a["roadworthiness"]["confidence"] == "INFERENCE"
    only_tow = intake.answer(intake.new_draft("owned_trailer"), "past_tow", "towed once", "seller_stated")
    only_tow["title"] = "BBQ trailer"
    b = owned_asset.comparison({"item_id": "x", "research": [{"field": f, "finding": __import__("json").dumps({"value": v, "entered_by": "michael"}), "basis": "FACT", "provenance_id": "prov_x"} for f, v, _ in owned_asset.answers_to_inputs(only_tow)]}, NOW)
    assert b["roadworthiness"]["confidence"] == "INFERENCE" and b["sunk_basis"]["historical_basis_usd"] is None


def test_rehab_ranges_make_paths_compute_through_the_same_assembly(ledger_db):
    d = _draft(minimal_rehab_cash="$200-$300", themed_rehab_cash="$600-$900")
    assert {"owned:minimal:cash", "owned:themed:cash"} <= {f for f, _, _ in owned_asset.answers_to_inputs(d)}
    card = _run(ledger_db, d)
    assert "owned_asset: owned:minimal:resale" in card["unknowns"] and "owned_asset: owned:minimal:cash" not in card["unknowns"]
