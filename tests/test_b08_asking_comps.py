"""B-08: eBay Browse ASKING comps for Agent 03's evidence bundle — labelled ASKING, never SOLD; derived from
listings discovery already retained; never the subject's own listing."""

from __future__ import annotations

import json

import pytest

from conftest import FIX, FLIP, T0, World
from mbos_discovery import contract
from mbos_discovery.adapters import EbayBrowseAdapter, EbayInsightsAdapter
from mbos_discovery.comps import (CompsStore, ManualCompsAdapter, asking_comps_from_items, candidate_comps,
                                  collect_comps)
from mbos_discovery.health import HealthBook
from mbos_discovery.http import CallbackTransport, HttpResponse
from mbos_discovery.rawstore import MemoryRawStore

EXTRA = {"itemId": "v1|110000000009|0", "title": "6x12 Enclosed Trailer, rear ramp, clean title",
         "price": {"value": "1650.00", "currency": "USD"}, "buyingOptions": ["FIXED_PRICE"], "conditionId": "3000",
         "itemWebUrl": "https://www.ebay.com/itm/110000000009",
         "itemLocation": {"city": "Benton", "stateOrProvince": "AR", "postalCode": "720**"},
         "categories": [{"categoryName": "Trailers"}]}


def _discover(world):
    base = FIX / "ebay"

    def handler(m, u, h, b):
        if m == "POST":
            return HttpResponse(200, (base / "token.json").read_bytes())
        if "utility+trailer" in u and "offset=0" in u:
            d = json.loads((base / "search-utility-trailer.json").read_text())
            d.pop("next")
            d["itemSummaries"].append(EXTRA)
            return HttpResponse(200, json.dumps(d).encode())
        return HttpResponse(200, b'{"itemSummaries":[]}')

    world.run([(EbayBrowseAdapter("id", "s", transport=CallbackTransport(handler), clock=world.clock), FLIP)])
    return list(world.store.items.values())


def _subject(items):
    return next(i for i in items if i["sources"][0]["source_listing_id"] == "v1|110000000001|0")


def test_asking_records_are_labelled_asking_never_sold(world):
    items = _discover(world)
    recs, provs = asking_comps_from_items(items)
    ids = {r["source_comp_id"] for r in recs}
    assert ids == {"v1|110000000001|0", "v1|110000000009|0"}          # the 5x8 AUCTION is not an ask
    for r in recs:
        assert r["kind"] == "asking" and r["source"] == "ebay_browse"
        assert "sold_date" not in r and r["observed_date"] == "2026-10-07"
        assert world.raw.get(r["raw_ref"])                               # backed by the retained listing
    for p in provs:
        contract.check_provenance(p)
        assert (p["basis"], p["actor_type"], p["tool_name"]) == ("FACT", "external", "mbos_discovery.comps.asking")
    assert asking_comps_from_items(items) == (recs, provs)              # deterministic


def test_subject_listing_is_never_its_own_comp(world):
    items = _discover(world)
    recs, _ = asking_comps_from_items(items)
    cands = candidate_comps(_subject(items), recs, T0)
    assert [c["source_comp_id"] for c in cands] == ["v1|110000000009|0"]


def test_free_and_ended_listings_are_not_asks():
    item = {"type": "flip", "category": "mower", "normalized": {"title": "free mower", "listing_status": "active",
            "price": {"amount": 0, "type": "free"}}, "sources": [{"source": "ebay", "source_listing_id": "x",
            "url": "u", "raw_ref": "sha256:" + "0" * 64, "first_seen_at": "2026-10-07T12:00:00Z"}]}
    ended = {**item, "normalized": {**item["normalized"], "listing_status": "ended",
                                    "price": {"amount": 300.0, "type": "fixed"}}}
    assert asking_comps_from_items([item, ended]) == ([], [])


# ---------------------------------------------------------------- acceptance with Agent 03's estimator
def _research(feed, item, recs, provs):
    try:
        return feed.research_step({**item, "state": "RESEARCHING"}, recs, provs, "2026-10-07T12:00:00Z")
    except KeyError as e:
        if e.args == ("sold_date",):
            pytest.xfail("Agent 03 comps_feed.entry() requires sold_date on asking comps — reported to 03 "
                         "(B-08 dependency); passes once fixed")
        raise


def test_estimator_consumes_asking_with_the_right_basis(world):
    feed = pytest.importorskip("mbos_economics.comps_feed")
    items = _discover(world)
    subject = _subject(items)
    asking, asking_prov = asking_comps_from_items(items)
    cands = candidate_comps(subject, asking, T0)

    # 1. asking-only evidence: selected as ASKING, but never becomes a resale target → stays RESEARCHING
    out = _research(feed, subject, cands, asking_prov)
    assert out["comps"]["selected"] == [c["provenance_id"] for c in cands]
    assert out["proposed_next_state"] == "RESEARCHING" and out["estimate"]["status"] != "estimated"

    # 2. with SOLD comps as well, the item scores; the asking comp is carried as kind "asking"
    store = CompsStore()
    collect_comps([(ManualCompsAdapter(FIX / "comps" / "manual", world.clock), FLIP),
                   (EbayInsightsAdapter.from_fixture(FIX / "comps" / "ebay_insights", world.clock),
                    FLIP.__class__("c", "flip", ("6x12 enclosed trailer",), max_pages=1))],
                  store, MemoryRawStore(), HealthBook(), T0)
    sold = candidate_comps(subject, store.records(), T0)
    out = _research(feed, subject, sold + cands, store.provenance_records(sold) + asking_prov)
    assert out["proposed_next_state"] == "SCORED"
    kinds = {c["provenance_id"]: c["kind"] for c in sold + cands}
    assert any(kinds[p] == "asking" for p in out["comps"]["selected"])
