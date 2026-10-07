"""C-04 lane-B side: sold-comps sources (manual + eBay Marketplace Insights), comp records in the hand-off
shape agreed with Agent 03, FACT provenance per comp, dedup, gating, and the candidate pre-filter."""

from __future__ import annotations

import json
import shutil

import pytest

from conftest import FIX, FLIP, T0, World
from mbos_discovery import contract
from mbos_discovery.adapter import SearchProfile
from mbos_discovery.adapters import EbayBrowseAdapter, EbayInsightsAdapter
from mbos_discovery.comps import CompsStore, ManualCompsAdapter, candidate_comps, collect_comps
from mbos_discovery.health import HealthBook, capability_for
from mbos_discovery.http import CallbackTransport, HttpResponse
from mbos_discovery.rawstore import MemoryRawStore

COMPS = SearchProfile("comps-trailer", "flip", ("6x12 enclosed trailer",), limit=50, max_pages=1)
RECORD_KEYS = {"comp_id", "kind", "price", "currency", "sold_date", "source", "source_comp_id", "url", "category",
               "title", "condition", "fetched_at", "raw_ref", "provenance_id"}


@pytest.fixture
def env(world):
    store, raw, health = CompsStore(), MemoryRawStore(), HealthBook()
    def run(jobs, **kw):
        return collect_comps(jobs, store, raw, health, world.clock(), **kw)
    return world, store, raw, health, run


def _manual(world, inbox=FIX / "comps" / "manual"):
    return ManualCompsAdapter(inbox, world.clock)


def test_manual_comps_shape_and_provenance(env):
    world, store, raw, _, run = env
    rep = run([(_manual(world), COMPS)])
    row, = rep.sources
    assert (row["added"], row["quarantined"]) == (6, 2)               # m5 future date, m6 no entered_by
    for rec in store.records():
        assert RECORD_KEYS <= set(rec) and "sold_price" not in rec    # `price` only (03 amendment a)
        assert rec["kind"] == "sold" and rec["price"] > 0 and rec["currency"] == "USD"
        assert raw.get(rec["raw_ref"])                                 # raw retained (03 amendment 2)
        prov = store.provenance[rec["provenance_id"]]
        contract.check_provenance(prov)
        assert (prov["actor_type"], prov["basis"], prov["human_actor"]) == ("human", "FACT", "michael")
        assert prov["fetched_at"] == rec["fetched_at"] == "2026-10-07T12:00:00Z"   # 03 amendment 1
    by_id = {r["source_comp_id"]: r for r in store.records()}
    assert by_id["m7"]["condition"] == "parts"                          # 03 routes these to as_is_comps
    assert by_id["m4"]["category"] == "generator"


def test_comp_dedup_and_update_keep_identity(env, tmp_path):
    world, store, _, _, run = env
    inbox = tmp_path / "inbox"
    shutil.copytree(FIX / "comps" / "manual", inbox)
    run([(_manual(world, inbox), COMPS)])
    ids = set(store.comps)
    rep = run([(_manual(world, inbox), COMPS)])
    assert rep.sources[0]["seen"] == 6 and set(store.comps) == ids
    m1 = json.loads((inbox / "m1.json").read_text()) | {"sold_price": 1800, "sold_date": "2026-09-21"}
    (inbox / "m1.json").write_text(json.dumps(m1))                    # human corrects the entry
    rep = run([(_manual(world, inbox), COMPS)])
    assert rep.sources[0]["updated"] == 1 and set(store.comps) == ids  # same comp_id even with a new date
    assert next(r for r in store.records() if r["source_comp_id"] == "m1")["price"] == 1800


def test_insights_requires_explicit_live_and_uses_restricted_scope(env):
    world, store, _, _, run = env
    calls = []
    ad = EbayInsightsAdapter("id", "s", transport=CallbackTransport(lambda *a: calls.append(a)), clock=world.clock)
    rep = run([(ad, COMPS)])
    assert rep.sources[0]["status"] == "error" and "not enabled" in rep.sources[0]["error"]["message"] and calls == []
    seen = []

    def handler(m, u, h, b):
        seen.append((m, u, b))
        return HttpResponse(200, (FIX / "ebay" / "token.json").read_bytes()) if m == "POST" else HttpResponse(200, b'{"itemSales":[]}')

    EbayInsightsAdapter("id", "s", live=True, transport=CallbackTransport(handler), clock=world.clock).fetch(COMPS)
    assert b"buy.marketplace.insights" in seen[0][2]
    assert seen[1][1].startswith("https://api.ebay.com/buy/marketplace_insights/v1_beta/item_sales/search?")


def test_insights_fixture_comps_are_external_fact(env):
    world, store, _, _, run = env
    rep = run([(EbayInsightsAdapter.from_fixture(FIX / "comps" / "ebay_insights", world.clock), COMPS)])
    assert (rep.sources[0]["added"], rep.sources[0]["quarantined"]) == (3, 1)   # one sale has no price
    for rec in store.records():
        prov = store.provenance[rec["provenance_id"]]
        assert (prov["actor_type"], prov["basis"]) == ("external", "FACT") and "human_actor" not in prov
        contract.check_provenance(prov)
    assert {r["sold_date"] for r in store.records()} == {"2026-09-25", "2026-09-02", "2026-07-15"}


def test_comp_sources_share_the_discovery_gate(env):
    world, store, _, health, run = env

    class Panic:
        def read(self):
            class S:
                def blocks(self, a, cap, cat):
                    return [f"PANIC_L2_CAPABILITY:{cap}"] if cap == capability_for("manual") else []
            return S()

    rep = run([(_manual(world), COMPS)], panic=Panic())
    assert rep.sources[0]["status"] == "skipped" and not store.comps
    ad = EbayInsightsAdapter("id", "s", live=True, clock=world.clock,
                             transport=CallbackTransport(lambda m, *a: HttpResponse(200, b'{"access_token":"t","expires_in":7200}')
                                                         if m == "POST" else HttpResponse(429, b"slow")))
    run([(ad, COMPS)])
    rep = run([(ad, COMPS)])
    assert rep.freeze_requests[0]["capability"] == "discovery.source.ebay_marketplace_insights.read"
    assert run([(ad, COMPS)]).sources[0]["status"] == "skipped"


def _trailer_item(world):
    world.run([(EbayBrowseAdapter.from_fixture(FIX / "ebay", world.clock), FLIP)])
    return next(i for i in world.store.items.values() if i["sources"][0]["source_listing_id"] == "v1|110000000001|0")


def test_candidate_comps_prefilter(env):
    world, store, _, _, run = env
    run([(_manual(world), COMPS), (EbayInsightsAdapter.from_fixture(FIX / "comps" / "ebay_insights", world.clock), COMPS)])
    item = _trailer_item(world)
    cands = candidate_comps(item, store.records(), T0)
    ids = [c["source_comp_id"] for c in cands]
    assert "m4" not in ids                                              # other category
    assert "m8" not in ids                                              # sold > 365 days before as_of
    assert {"m1", "v1|330000000003|0"} <= set(ids)
    assert cands == candidate_comps(item, list(reversed(store.records())), T0)   # order-independent
    assert candidate_comps({**item, "type": "service"}, store.records(), T0) == []


def test_comps_never_become_items(env):
    world, store, _, _, run = env
    run([(_manual(world), COMPS)])
    assert world.store.items == {}


# ---------------------------------------------------------------- end to end with Agent 03 (C-04 acceptance)
def test_flip_with_comps_advances_to_scored_with_fact_comp_provenance(env):
    feed = pytest.importorskip("mbos_economics.comps_feed")
    from mbos_economics.config import load_config
    from mbos_economics.estimate import load_priors
    cfg_dir = FIX / "econ_config_882c726"                       # pinned copy of 03's config (wheel ships none)
    world, store, _, _, run = env
    run([(_manual(world), COMPS), (EbayInsightsAdapter.from_fixture(FIX / "comps" / "ebay_insights", world.clock), COMPS)])
    item = _trailer_item(world)
    item = {**item, "state": "RESEARCHING"}
    recs = candidate_comps(item, store.records(), T0)
    out = feed.research_step(item, recs, store.provenance_records(recs), "2026-10-07T12:00:00Z",
                             cfg=load_config(config_dir=cfg_dir), priors=load_priors(config_dir=cfg_dir))
    assert out["proposed_next_state"] == "SCORED", (out["comps"]["rejected"], out["estimate"])
    assert out["comps"]["selected"] and set(out["comps"]["selected"]) <= {c["provenance_id"] for c in recs}
    used = [p for p in out["provenance_records"] if p["provenance_id"] in set(out["comps"]["selected"])]
    assert used and all(p["basis"] == "FACT" for p in used)               # FACT-tagged comp provenance
    research = out["item"].get("research", [])
    assert any(r["provenance_id"] in set(out["comps"]["selected"]) and r["basis"] == "FACT" for r in research)
