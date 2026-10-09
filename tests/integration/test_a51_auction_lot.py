"""A-51: a B-23 auction lot (fixture) through the spine to a scored Item and card on lane C's C-32/C-33 auction model.

First real case: the CountyLine 32-ton splitter (current bid 450, 24 bids, Michael's resale target 1500). DRY-RUN; no bid path."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone

import pytest

from mbos import auction_lot, spine
from mbos import card as cardmod
from mbos.contracts import schemas
from mbos.interfaces import RawListing
from mbos.runtime import Components
from tests.helpers.common import ROOT

pytest.importorskip("mbos_economics.asset_deal")
pytest.importorskip("mbos_discovery.auctions")
FIX = ROOT / "tests/fixtures/auctions"
SEEN = datetime(2026, 10, 9, 23, 10, tzinfo=timezone.utc)
SPLITTER = {"asset_class": "component_machine", "pickup_cost": 0, "transport_cost": 25, "labor_hours": 2, "days_to_sell": 7,
            "pickup_wait_hours": 24, "comps": [{"sold_price": 800, "source": "fixture sold"}, {"sold_price": 900, "source": "fixture sold"},
                                               {"sold_price": 1000, "source": "fixture sold"}, {"asking_price": 1500, "status": "asking"},
                                               {"asking_price": 1800, "status": "asking"}],
            "owner_resale_target": {"value": 1500, "source": "Michael 2026-10-09", "note": "system estimate about $900"}}


def _ingest(engine, inputs):
    from mbos_discovery.adapter import SearchProfile
    from mbos_discovery.auctions import AuctionFixtureAdapter
    from mbos_discovery.spine import SpineNormalizer

    adapter = AuctionFixtureAdapter("hibid", FIX, clock=lambda: SEEN)
    res = adapter.fetch(SearchProfile("a51", "flip"))  # fixture file only; never the network
    assert res.ok and len(res.records) == 1
    rec = res.records[0]
    raw = RawListing(source="hibid", source_listing_id="CL32-1", url="https://example.invalid/hibid/rules", fetched_at=SEEN.isoformat(),
                     ingestion_method=adapter.ingestion_method, tos_risk=adapter.tos_risk, payload=rec.payload)
    norm = SpineNormalizer({"hibid": adapter}).normalize(raw)
    assert norm.opportunity_kind == "auction_lot"
    comps = Components().with_defaults()
    with engine.begin() as c:
        iid = spine.ingest(c, *auction_lot.conform(asdict(raw), asdict(norm)), "hibid:a51", adapter.adapter_version, comps)["item_id"]
    with engine.begin() as c:
        assert spine.read_item(c, iid)["opportunity_kind"] == "auction_lot"
        assert auction_lot.attach_lot(c, iid, adapter.lot(rec.payload, rec.fetched_at)) == 5
        assert auction_lot.attach_inputs(c, iid, inputs, "michael") == len(inputs)
    return iid


def _score(engine, iid):
    from mbos.adapters.economics import EconomicsEngineScorer, EconomicsEnricher

    with engine.begin() as c:
        item = spine.read_item(c, iid)
    sr = EconomicsEngineScorer().score(item)
    assert sr == EconomicsEngineScorer().score(item), "deterministic"
    assert not schemas.errors("scorecard", sr.scorecard)
    with engine.begin() as c:
        spine.record_score(c, iid, asdict(sr))
    with engine.begin() as c:
        assert EconomicsEnricher().enrich(c, spine, iid) == 1
    with engine.connect() as c:
        item, receipts, areqs = cardmod.load_inputs(c, iid)
        return sr, item, areqs, cardmod.build_card(item, receipts, areqs, cardmod.enrichment_from_item(c, item))


def test_countyline_splitter_lot_in_scored_item_and_card_out(ledger_db):
    sr, item, areqs, card = _score(ledger_db, _ingest(ledger_db, SPLITTER))
    assert not schemas.errors("item", item) and item["state"] == "RECOMMENDED"
    a = item["scores"]["scorecard"]["auction"]
    assert a["lot"]["current_bid"] == 450 and a["lot"]["bid_count"] == 24 and a["lot"]["closes_at"] == "2026-10-10T23:00:00Z"
    assert a["lot"]["buyer_premium_pct"] == 10 and a["lot"]["sales_tax_pct"] == 9.5 and a["lot"]["pickup"].startswith("Pickup")
    # all-in at the current bid: 450 + 45 premium + 47.03 tax on 495 + 25 transport
    assert a["cost"] == {"hammer": 450, "buyer_premium": 45, "sales_tax": 47.03, "pickup_and_transport": 25, "all_in": 567.03}
    assert a["all_in_cost"] == 567.03 and a["capital_tied_up"] == 567.03
    assert a["resale"] == {"system_estimate": 900, "owner_target": 1500, "used": "owner",
                           "owner_provenance": {"source": "Michael 2026-10-09", "note": "system estimate about $900", "basis": "HUMAN-ATTESTED"}}
    assert a["net"]["expected"] == round(1500 - 567.03, 2) and a["days_to_cash"] > 0 and a["profit_per_day"] > 0
    assert a["cash_cap"] == {"cap": 500, "over_cap": True}
    assert a["suggested_max_bid"]["binding"] == "cash_cap" and a["suggested_max_bid"]["max_bid"] == 394.35  # (500-25)/(1.1*1.095)
    fc = a["bid_forecast"]
    assert fc["label"].startswith("FORECAST") and fc["hours_left"] == 24 and fc["final_hammer"]["expected"] == 630 and fc["likely_exceeds_max_bid"]
    assert a["evidence"]["sold_comps_count"] == 3 and a["evidence"]["asking_comps_count"] == 2 and not a["evidence"]["asking_counted_as_sold"]
    assert sr.verdict == "MAYBE" and any("exceeds cap 500" in r for r in sr.rationale) and any("owner resale target" in r for r in sr.rationale)
    # the card: the existing fields carry the figures; the full block (with the labelled forecast) is the value-add plan
    assert cardmod.validate_card(card) == [], cardmod.validate_card(card)
    flat = str(card)
    assert "394.35" in flat and "567.03" in flat
    assert card["value_add_plan"]["plan"]["value"]["bid_forecast"]["label"].startswith("FORECAST")
    assert not areqs and not item["recommendation"].get("proposed_actions"), "no bid path, no action proposed"


@pytest.mark.parametrize("kind", ["sold", "asking"])
def test_asking_only_comps_still_cannot_yes(ledger_db, kind):
    prices = (1100, 1200, 1300)
    comps = [{"sold_price": p} if kind == "sold" else {"asking_price": p, "status": "asking"} for p in prices]
    inputs = {**{k: v for k, v in SPLITTER.items() if k != "owner_resale_target"}, "comps": comps, "cash_cap_per_buy": 2000}
    sr, item, _, _ = _score(ledger_db, _ingest(ledger_db, inputs))
    if kind == "sold":
        assert sr.verdict == "YES"  # control: the same prices as SOLD comps clear every gate
    else:
        assert sr.verdict == "MAYBE" and item["recommendation"]["verdict"] != "YES"
        assert item["scores"]["scorecard"]["auction"]["evidence"]["asking_comps_count"] == 3
        assert any("sold_comps_or_parts" in r for r in sr.rationale)


def test_lot_without_auction_inputs_keeps_the_existing_engine_path():
    assert not auction_lot.is_auction({"opportunity_kind": "auction_lot", "research": []})
    assert not auction_lot.is_auction({"opportunity_kind": "buy_item", "research": [{"field": "auction:x", "finding": '{"value": 1}'}]})
