"""A-20: lane enrichers in the workflow; atomic append (04 D-16) so concurrent lanes never lose each other's blocks."""

from __future__ import annotations

import threading

import pytest
import sqlalchemy as sa

from mbos import card as cardmod
from mbos import ledger, spine
from tests.helpers.seed import seed_flow


def test_concurrent_lanes_never_lose_each_others_blocks_reference(ledger_db):
    ids = seed_flow(ledger_db, act=False)
    blocks = ["listing_activity", "seller", "economics", "logistics", "seasonality", "why"]
    errors = []

    def lane(block):
        try:
            with ledger_db.begin() as c:
                prov = ledger.tool_provenance(c, f"lane.{block}")
                data = {"why": [f"reason for {block}"]} if block == "why" else {"note": {"value": block, "basis": "INFERENCE"}}
                spine.record_enrichment(c, ids["item_id"], block, data, prov, agent=f"agent-{block}")
        except Exception as e:  # pragma: no cover
            errors.append(e)

    ts = [threading.Thread(target=lane, args=(b,)) for b in blocks]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors, errors
    with ledger_db.connect() as c:
        item = spine.read_item(c, ids["item_id"])
    assert sorted(r["field"] for r in item["research"] if r["field"].startswith("card.")) == sorted(f"card.{b}" for b in blocks)


def test_same_block_twice_is_a_noop(ledger_db):
    ids = seed_flow(ledger_db, act=False)
    with ledger_db.begin() as c:
        prov = ledger.tool_provenance(c, "lane.x")
        spine.record_enrichment(c, ids["item_id"], "seller", {"confidence": "low"}, prov)
    with ledger_db.begin() as c:
        n0 = c.execute(sa.text("SELECT count(*) FROM mbos.receipts")).scalar_one()
        prov = ledger.tool_provenance(c, "lane.x")
        spine.record_enrichment(c, ids["item_id"], "seller", {"confidence": "low"}, prov)
        n1 = c.execute(sa.text("SELECT count(*) FROM mbos.receipts")).scalar_one()
    assert n1 == n0, "no second ITEM receipt for identical content"


def test_real_lane_c_enricher_in_the_card(ledger_db):
    pytest.importorskip("mbos_economics.enrich")
    from dataclasses import asdict

    from mbos.adapters.economics import EconomicsEngineScorer, EconomicsEnricher
    from mbos.reference.fixture_adapter import FixtureNormalizer
    from mbos.runtime import Components
    from tests.helpers.common import FIXTURE
    from mbos.reference.fixture_adapter import FixtureSourceAdapter

    comps = Components().with_defaults()
    raw = next(r for r in FixtureSourceAdapter(FIXTURE).fetch() if r.source_listing_id == "FIX-TRAILER-1")
    with ledger_db.begin() as c:
        item_id = spine.ingest(c, asdict(raw), asdict(FixtureNormalizer().normalize(raw)), "fx", "0", comps)["item_id"]
    with ledger_db.begin() as c:
        assert EconomicsEnricher().enrich(c, spine, item_id) == 0  # not scored by lane C yet: attaches nothing, no crash
        sr = EconomicsEngineScorer().score(spine.read_item(c, item_id))
    with ledger_db.begin() as c:
        spine.record_score(c, item_id, asdict(sr))
    with ledger_db.begin() as c:
        n = EconomicsEnricher().enrich(c, spine, item_id)
    assert n >= 1
    with ledger_db.begin() as c:
        assert EconomicsEnricher().enrich(c, spine, item_id) == n  # re-run: same blocks, attaches nothing new
    with ledger_db.connect() as c:
        item, receipts, areqs = cardmod.load_inputs(c, item_id)
        fields = [r["field"] for r in item["research"] if r["field"].startswith("card.")]
        card = cardmod.build_card(item, receipts, areqs, cardmod.enrichment_from_item(c, item))
    assert len(fields) == len(set(fields)) == n, fields
    assert "card.value_add" in fields, "C-16: a plan from the deal's own numbers is attached"
    assert cardmod.validate_card(card) == [], cardmod.validate_card(card)
    assert card["logistics"]["trailer_owned"]["value"] is False
    assert any(not x.startswith("Asking") for x in card["why"]), "lane C's plain-English reasons are on the card"
