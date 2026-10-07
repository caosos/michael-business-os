"""Normalization is deterministic: same bytes → same output, two independent runs → identical
state, and any Item can be re-derived from its retained raw payload."""

import json

from conftest import FIX, World
from mbos_discovery.adapters import EbayBrowseAdapter, ServiceIntakeAdapter
from mbos_discovery.ids import parse_ts


def test_normalize_is_pure():
    ad = EbayBrowseAdapter.from_fixture(FIX / "ebay")
    summary = json.loads((FIX / "ebay" / "search-generator.json").read_text())["itemSummaries"][0]
    from conftest import T0
    a, b = ad.normalize(summary, T0), ad.normalize(json.loads(json.dumps(summary)), T0)
    assert a == b


def test_two_independent_runs_are_byte_identical():
    w1, w2 = World(), World()
    w1.run()
    w2.run()
    assert w1.dump() == w2.dump()
    assert sorted(w1.store.items) == sorted(w2.store.items)


def test_item_replays_from_raw_ref(world):
    world.run()
    adapters = {a.source: a for a, _ in world.jobs()}
    for item in world.store.items.values():
        primary = item["sources"][0]
        prov = world.store.provenance[primary["provenance_id"]]
        payload = json.loads(world.raw.get(primary["raw_ref"]))
        n = adapters[primary["source"]].normalize(payload, parse_ts(prov["fetched_at"]))
        assert n.normalized == item["normalized"], item["item_id"]
        assert (n.type, n.category) == (item["type"], item["category"])


def test_ids_are_derived_not_random():
    w1, w2 = World(), World()
    w1.run()
    w2.clock.advance(hours=1)       # later run, fresh store: listing ids identical, time part differs
    w2.run()
    l1 = {s["source_listing_id"]: i for i, it in w1.store.items.items() for s in it["sources"]}
    l2 = {s["source_listing_id"]: i for i, it in w2.store.items.items() for s in it["sources"]}
    assert l1.keys() == l2.keys()
    assert all(l1[k][-16:] == l2[k][-16:] for k in l1)   # hash tail is stable


def test_classification_prefers_headline_over_description():
    ad = ServiceIntakeAdapter("website_lead", FIX / "intake" / "website_form")
    from conftest import T0
    n = ad.normalize({"submission_id": "x", "received_at": "2026-10-06T00:00:00Z",
                      "service_requested": "Mount TV", "description": "65in TV on drywall"}, T0)
    assert n.category == "smart_home_install"
